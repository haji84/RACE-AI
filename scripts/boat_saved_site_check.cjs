'use strict';
/* Read-only proof against the existing private owner view. Never print its URL. */
const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {AsyncLocalStorage}=require('node:async_hooks');
const Simulation=require('./boat_saved_simulation_context.cjs');

const diagnosticStore=new AsyncLocalStorage(),diagnosticErrors=new WeakMap();
const phases=new Set(['context_read','context_validation','browser_launch','page_setup','owner_navigation','saved_view_load','presentation','feed_generation','selected_day','race_lifecycle','venue_results','race_detail','native_probe','compact_results','research_audit','saved_result_metrics','simulation_controls','simulation_labels','numeric_capture','numeric_snapshot','historical_day','current_day_lifecycle','viewport_overflow','final_integrity','final_generation','final_day','browser_cleanup']);
const fields=new Set(['day','generation','group_sha256','daily_budget','race_budget','metric_layout','observed.available','observed.hits','observed.misses','observed.pending','observed.void','observed.review','observed.hit_rate','observed.denominator','observed.races','observed.no_forecast_review','lifecycle.upcoming','lifecycle.unknown','lifecycle.closed','spent','bought','held','unspent','payout','refund','settledNet','settledStake','pendingStake','net','balance','roi','settledCount','bought_hit_rate','bought_denominator','budget_per_day','budget_days']);
const errorClasses=new Set(['Error','AssertionError','TimeoutError','TypeError','RangeError','SyntaxError','ReferenceError','URIError']);
const errorCodes=new Set(['ERR_ASSERTION','ENOENT','EACCES','ENOTDIR','EINVAL','ETIMEDOUT','ECONNRESET','MODULE_NOT_FOUND','ERR_MODULE_NOT_FOUND','ERR_INVALID_URL','ERR_INVALID_ARG_TYPE','ERR_INVALID_ARG_VALUE','ERR_OUT_OF_RANGE']);
function ownedLine(skip){
  try{
    const site={};Error.captureStackTrace(site,skip);
    const escaped=__filename.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
    const found=site.stack.match(new RegExp(escaped+':(\\d+):\\d+'));const line=Number(found?.[1]);
    return Number.isSafeInteger(line)&&line>0&&line<100000?line:1;
  }catch{return 1;}
}
function diagnosticPhase(phase,width){
  const state=diagnosticStore.getStore();if(!state)return;
  state.phase=phases.has(phase)?phase:'context_validation';state.line=ownedLine(diagnosticPhase);state.numeric_field=null;
  if(width!==undefined)state.width=[320,390,1440,1920].includes(width)?width:null;
}
function diagnosticField(field){
  const state=diagnosticStore.getStore();if(!state)return;
  state.numeric_field=fields.has(field)?field:null;state.line=ownedLine(diagnosticField);
}
function diagnosticCompleted(){const state=diagnosticStore.getStore();if(state)state.completed_numeric_scenarios++;}
function safeDiagnostic(error,state){
  const trait=(key,allowed,fallback)=>{let value;try{value=error?.[key];}catch{}return allowed.has(value)?value:fallback;};
  return {phase:phases.has(state.phase)?state.phase:'context_read',width:[320,390,1440,1920].includes(state.width)?state.width:null,
    completed_numeric_scenarios:Number.isSafeInteger(state.completed_numeric_scenarios)&&state.completed_numeric_scenarios>=0&&state.completed_numeric_scenarios<=12?state.completed_numeric_scenarios:0,
    script:'boat_saved_site_check.cjs',line:Number.isSafeInteger(state.line)&&state.line>0&&state.line<100000?state.line:1,
    error_class:trait('name',errorClasses,'UNRECOGNIZED_ERROR'),error_code:trait('code',errorCodes,null),numeric_field:fields.has(state.numeric_field)?state.numeric_field:null};
}
async function withDiagnostics(operation){
  const state={phase:'context_validation',width:null,completed_numeric_scenarios:0,line:ownedLine(withDiagnostics),numeric_field:null};
  return diagnosticStore.run(state,async()=>{
    try{return await operation();}catch(error){
      if(error!==null&&['object','function'].includes(typeof error))diagnosticErrors.set(error,safeDiagnostic(error,state));
      throw error;
    }
  });
}
function failureReport(error){
  const diagnostic=error!==null&&['object','function'].includes(typeof error)?diagnosticErrors.get(error):null;
  return {status:'LIVE_OWNER_SITE_REJECTED',reason:'SAVED_SITE_BROWSER_CHECK_FAILED',diagnostic:diagnostic||safeDiagnostic(error,{phase:'context_read',line:ownedLine(failureReport)})};
}

const allowedHosts=new Set(['haji84.github.io','api.github.com','raw.githubusercontent.com']);
function requestAdmission(request,key){
  try{
    const body=request.postData()||'',details=request.url()+JSON.stringify(request.headers())+body;
    const leaked=details.includes(key),url=new URL(request.url());
    const allowed=!leaked&&!body&&['GET','HEAD'].includes(request.method())&&
      (['data:','blob:'].includes(url.protocol)||url.protocol==='https:'&&allowedHosts.has(url.hostname));
    return {allowed,leaked};
  }catch{return {allowed:false,leaked:false};}
}
async function revealRace(page,raceId,dayRaces){
  assert.match(raceId,/^\d{8}-\d{2}-\d{2}$/);
  assert.ok(Number.isSafeInteger(dayRaces)&&dayRaces>=1&&dayRaces<=288);
  const target=page.locator('#page-races [data-open-race="'+raceId+'"]');
  for(let block=0;await target.count()===0;block++){
    assert.ok(block<Math.ceil(dayRaces/60)-1);
    const more=page.getByRole('button',{name:/さらに60件表示/});
    assert.ok(await more.isVisible());await more.click();
  }
  return target;
}
function requireNativeGroups(context,values){
  const actual=new Set();
  for(const value of values){
    let parts;try{parts=JSON.parse(value);}catch{continue;}
    if(Array.isArray(parts)&&parts[1]==='boat'&&parts[2]==='P1')
      actual.add(JSON.stringify([parts[3]??null,parts[4]??null,parts[5]??null,parts[6]??null]));
  }
  for(const expected of context.native_groups)assert.ok(actual.has(JSON.stringify(expected)));
}

const hash=value=>crypto.createHash('sha256').update(value).digest('hex');
const count=value=>Number.isSafeInteger(value)&&value>=0;
function keys(value,expected){
  assert.ok(value&&typeof value==='object'&&!Array.isArray(value));
  assert.deepEqual(Object.keys(value).sort(),[...expected].sort());
}
function counts(value,fields){keys(value,fields);for(const v of Object.values(value))assert.ok(count(v));}
function validateSimulationExpected(context){
  if(!Object.hasOwn(context,'simulation_expected')){
    assert.ok(context.numeric_simulation_required===undefined||context.numeric_simulation_required===false);return null;
  }
  assert.equal(context.numeric_simulation_required,true);
  const value=context.simulation_expected;
  keys(value,['schema','day','generation','group_sha256','eligible_native_races','issued_races','observed','observed_closed','lifecycle','scenarios','budget_cap_exercised','budget_cap_coverage']);
  assert.equal(value.schema,Simulation.schema);assert.equal(value.day,context.day);assert.equal(value.generation,context.generation);
  assert.ok(count(value.generation)&&value.generation>0);assert.match(value.group_sha256,/^[a-f0-9]{64}$/);
  counts(value.observed,Simulation.observedFields);counts(value.observed_closed,Simulation.observedFields);
  assert.equal(value.observed.races,context.day_races);assert.ok(value.observed.available<=value.observed.races);
  for(const c of [value.observed,value.observed_closed]){
    assert.equal(Simulation.comparisonFields.reduce((n,k)=>n+c[k],0),c.races);assert.ok(c.available<=c.races);
  }
  assert.ok(count(value.eligible_native_races)&&value.eligible_native_races>0&&count(value.issued_races));
  assert.ok(value.eligible_native_races<=value.issued_races&&value.issued_races<=value.observed.races);
  keys(value.lifecycle,['as_of','closed','upcoming','unknown']);
  assert.equal(value.lifecycle.as_of,context.simulation_as_of);
  assert.match(value.lifecycle.as_of,/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/);
  assert.ok(Number.isFinite(Date.parse(value.lifecycle.as_of)));
  for(const k of ['closed','upcoming','unknown'])assert.ok(count(value.lifecycle[k]));
  assert.equal(value.lifecycle.closed+value.lifecycle.upcoming+value.lifecycle.unknown,value.observed.races);
  assert.equal(value.observed_closed.races,value.lifecycle.closed);
  for(const k of ['available',...Simulation.comparisonFields])assert.ok(value.observed_closed[k]<=value.observed[k]);
  assert.ok(Array.isArray(value.scenarios)&&value.scenarios.length===4);
  const pairs=new Set();
  for(const s of value.scenarios){
    keys(s,[...Simulation.financialFields,'comparison','boughtComparison']);
    for(const k of Simulation.financialFields.filter(k=>!['settledNet','net','roi'].includes(k)))assert.ok(count(s[k]));
    for(const k of ['settledNet','net'])assert.ok(s[k]===null||Number.isSafeInteger(s[k]));
    assert.ok(s.roi===null||typeof s.roi==='number'&&Number.isFinite(s.roi)&&s.roi>=0);
    counts(s.comparison,Simulation.comparisonFields);counts(s.boughtComparison,Simulation.comparisonFields);
    for(const k of Simulation.comparisonFields)assert.equal(s.comparison[k],value.observed[k]);
    assert.equal(Object.values(s.boughtComparison).reduce((a,b)=>a+b,0),s.bought);assert.ok(s.bought<=value.observed.races);
    assert.equal(s.budgetTotal,s.budgetPerDay);
    const pair=s.budgetPerDay+':'+s.raceBudget;assert.ok(!pairs.has(pair));pairs.add(pair);
  }
  assert.deepEqual([...pairs].sort(),['10000:1000','10000:800','5000:1000','5000:800']);
  const capped=[800,1000].every(r=>value.scenarios.find(s=>s.budgetPerDay===10000&&s.raceBudget===r).bought>
    value.scenarios.find(s=>s.budgetPerDay===5000&&s.raceBudget===r).bought);
  assert.equal(value.budget_cap_exercised,capped);
  assert.equal(value.budget_cap_coverage,capped?'EXERCISED':'INSUFFICIENT_ELIGIBLE_RACES');return value;
}
function requireSimulationGroup(context,values){
  const expected=validateSimulationExpected(context);assert.ok(expected&&Array.isArray(values));
  const matching=values.filter(value=>typeof value==='string'&&hash(value)===expected.group_sha256);
  assert.equal(matching.length,1);const parts=JSON.parse(matching[0]);
  assert.ok(Array.isArray(parts)&&[6,7].includes(parts.length));assert.equal(parts[1],'boat');assert.equal(parts[2],'P1');
  const identity=JSON.stringify([parts[3]??null,parts[4]??null,parts[5]??null,parts[6]??null]);
  assert.ok(context.native_groups.some(group=>JSON.stringify(group)===identity));return matching[0];
}
function metricMap(values){
  assert.ok(Array.isArray(values));const result=new Map();
  for(const value of values){
    for(const k of ['label','value','detail'])assert.equal(typeof value[k],'string');
    assert.ok(!result.has(value.label));result.set(value.label,value);
  }
  return result;
}
function capture(text,pattern){const found=text.match(pattern);assert.ok(found);return found.slice(1);}
function money(text,expected){
  if(expected===null){assert.equal(text,'未確定');return;}
  const [sign,digits]=capture(text,/^([＋-]?)(\d{1,3}(?:,\d{3})*|\d+)円$/);
  const value=Number((sign==='-'?'-':'')+digits.replaceAll(',',''));assert.ok(Number.isSafeInteger(value));assert.equal(value,expected);
}
function percentage(text,expected,empty){
  if(expected===null){assert.equal(text,empty);return;}
  const [digits]=capture(text,/^(\d+\.\d)%$/);assert.ok(Math.abs(Number(digits)-Number(expected.toFixed(1)))<1e-8);
}
function requireSimulationSnapshot(context,snapshot,dailyBudget,raceBudget){
  diagnosticPhase('numeric_snapshot');
  const expected=validateSimulationExpected(context);assert.ok(expected);
  diagnosticField('day');assert.equal(snapshot.day,expected.day);
  diagnosticField('generation');assert.equal(snapshot.generation,expected.generation);
  diagnosticField('group_sha256');assert.equal(snapshot.group_sha256,expected.group_sha256);
  diagnosticField('daily_budget');assert.equal(snapshot.daily_budget,dailyBudget);
  diagnosticField('race_budget');assert.equal(snapshot.race_budget,raceBudget);
  const s=expected.scenarios.find(s=>s.budgetPerDay===dailyBudget&&s.raceBudget===raceBudget);assert.ok(s);
  diagnosticField('metric_layout');
  const saved=metricMap(snapshot.saved_metrics),sim=metricMap(snapshot.simulation_metrics);
  const get=(map,label)=>{const value=map.get(label);assert.ok(value);return value;};
  const closed=saved.has('レース前'),c=closed?expected.observed_closed:expected.observed;
  for(const [label,key] of Object.entries({'取得結果':'available','的中':'hits','不的中':'misses','結果待ち':'pending','中止・返還':'void','照合保留':'review'})){
    diagnosticField('observed.'+key);
    assert.equal(get(saved,label).value,c[key]+'レース');
  }
  const hit=get(saved,'保存Top8的中率'),denominator=c.hits+c.misses;
  diagnosticField('observed.hit_rate');
  percentage(hit.value,denominator?c.hits/denominator*100:null,'算出対象なし');
  diagnosticField('observed.denominator');
  assert.deepEqual(capture(hit.detail,/^(\d+) \/ (\d+)レース/).map(Number),[c.hits,denominator]);
  diagnosticField('observed.races');
  assert.equal(Number(capture(snapshot.coverage,/対象\s+(\d+)レース/)[0]),expected.observed.races);
  diagnosticField('observed.no_forecast_review');
  assert.equal(Number(capture(snapshot.coverage,/未予想・照合不可\s+(\d+)/)[0]),c.noForecast+c.review);
  if(closed){
    diagnosticField('lifecycle.upcoming');
    assert.equal(get(saved,'レース前').value,expected.lifecycle.upcoming+'レース');
    diagnosticField('lifecycle.unknown');
    if(expected.lifecycle.unknown||saved.has('締切未確認'))assert.equal(get(saved,'締切未確認').value,expected.lifecycle.unknown+'レース');
    diagnosticField('lifecycle.closed');
    assert.equal(Number(capture(snapshot.coverage,/結果対象\s+(\d+)/)[0]),expected.lifecycle.closed);
  }
  diagnosticField('spent');const stake=get(sim,'予定購入額');money(stake.value,s.spent);
  diagnosticField('bought');assert.equal(Number(capture(stake.detail,/^(\d+)レース/)[0]),s.bought);
  diagnosticField('race_budget');
  money(capture(stake.detail,/上限([\d,]+円)\/レース/)[0],s.raceBudget);
  diagnosticField('unspent');const unused=get(sim,'未使用予算');money(unused.value,s.unspent);
  diagnosticField('budget_per_day');const [perDay,days]=capture(unused.detail,/1日\s+([\d,]+円)\s*×\s*(\d+)日/);money(perDay,s.budgetPerDay);
  diagnosticField('budget_days');assert.equal(Number(days),1);
  diagnosticField('held');
  money(capture(unused.detail,/追加未配分\s+([\d,]+円)/)[0],s.held);
  diagnosticField('payout');const payout=get(sim,'確認済み払戻');money(payout.value,s.payout);
  diagnosticField('refund');money(capture(payout.detail,/返還\s+([\d,]+円)/)[0],s.refund);
  diagnosticField('settledNet');const settled=get(sim,'確定分の収支');money(settled.value,s.settledNet);
  diagnosticField('settledStake');money(capture(settled.detail,/購入額\s+([\d,]+円)/)[0],s.settledStake);
  diagnosticField('pendingStake');
  money(get(sim,'未確定購入額').value,s.pendingStake);
  diagnosticField('net');const total=get(sim,'全体の収支');money(total.value,s.net);
  diagnosticField('balance');money(capture(total.detail,/仮の残高\s+([\d,]+円)/)[0],s.balance);
  diagnosticField('roi');
  percentage(get(sim,'確定分の回収率').value,s.roi,'未確定');
  diagnosticField('settledCount');
  assert.deepEqual(capture(get(sim,'収支確定の購入予定').value,/^(\d+) \/ (\d+)レース$/).map(Number),[s.settledCount,s.bought]);
  const bought=get(sim,'購入予定分の的中率'),n=s.boughtComparison.hits+s.boughtComparison.misses;
  diagnosticField('bought_hit_rate');
  percentage(bought.value,n?s.boughtComparison.hits/n*100:null,'算出対象なし');
  diagnosticField('bought_denominator');
  assert.deepEqual(capture(bought.detail,/^(\d+) \/ (\d+)レース/).map(Number),[s.boughtComparison.hits,n]);
}
async function readSimulationSnapshot(page){
  const value=await page.evaluate(()=>{
    const metrics=id=>[...document.querySelectorAll('#'+id+' .metric')].map(card=>({label:card.querySelector('.metric-label')?.textContent.trim(),value:card.querySelector('strong')?.textContent.trim(),detail:card.querySelector('small')?.textContent.trim()}));
    return {day:document.querySelector('#selected-date')?.value,generation:Number(document.querySelector('#saved-view-sync')?.dataset.generation),group_value:document.querySelector('#results-model')?.value,
      daily_budget:Number(document.querySelector('#simulation-budget')?.value),race_budget:Number(document.querySelector('#simulation-race-budget')?.value),coverage:document.querySelector('#result-coverage')?.textContent,
      saved_metrics:metrics('saved-result-metrics'),simulation_metrics:metrics('simulation-metrics')};
  });
  const {group_value:group,...snapshot}=value;assert.equal(typeof group,'string');return {...snapshot,group_sha256:hash(group)};
}
async function checkSimulationMetrics(page,context){
  diagnosticPhase('simulation_controls');
  const expected=validateSimulationExpected(context);let verified=0;
  if(expected){
    const group=requireSimulationGroup(context,await page.locator('#results-model option').evaluateAll(options=>options.map(option=>option.value)));
    await page.locator('#results-model').selectOption(group);
    assert.equal(await page.locator('#saved-result-metrics').isVisible(),true);assert.equal(await page.locator('#simulation-metrics').isVisible(),true);
  }
  for(const budget of ['10000','5000'])for(const race of expected?['800','1000']:['1000']){
    diagnosticPhase('simulation_controls');
    await page.locator('#simulation-budget').fill(budget);await page.locator('#simulation-budget').dispatchEvent('change');
    await page.locator('#simulation-race-budget').selectOption(race);
    assert.equal(await page.locator('#simulation-budget').inputValue(),budget);
    diagnosticPhase('simulation_labels');
    const simulation=await page.locator('#simulation-metrics').innerText();
    for(const label of ['確定分の収支','確定分の回収率','未確定購入額','全体の収支'])assert.ok(simulation.includes(label));
    assert.doesNotMatch(simulation,/試算を表示できません/);
    if(expected){diagnosticPhase('numeric_capture');requireSimulationSnapshot(context,await readSimulationSnapshot(page),Number(budget),Number(race));verified++;diagnosticCompleted();}
  }
  assert.equal(verified,expected?4:0);
  return {numeric_simulation_verified:expected!==null,numeric_simulation_scenarios_checked:verified};
}

function validate(context){
  assert.equal(context.schema,'RACE_AI_PRIVATE_LIVE_SITE_CHECK_CONTEXT_V1');
  const url=new URL(context.owner_url);
  assert.equal(url.origin,'https://haji84.github.io');
  assert.equal(url.pathname,'/RACE-AI/');assert.equal(url.search,'');
  assert.equal(url.username,'');assert.equal(url.password,'');
  assert.match(url.hash,/^#saved=[a-f0-9]{64}\.[A-Za-z0-9_-]{43}$/);
  assert.match(context.day,/^\d{4}-\d{2}-\d{2}$/);
  dateEvidence(context,0,0);
  assert.ok(Number.isSafeInteger(context.generation)&&context.generation>0);
  for(const name of ['minimum_results','native_p1_groups','old_completed'])
    assert.ok(Number.isSafeInteger(context[name])&&context[name]>=0);
  assert.ok(context.native_p1_groups>0);
  assert.ok(Number.isSafeInteger(context.day_races)&&context.day_races>=1&&context.day_races<=288);
  assert.ok(Array.isArray(context.native_groups)&&context.native_groups.length===context.native_p1_groups);
  for(const group of context.native_groups){
    assert.ok(Array.isArray(group)&&group.length===4&&typeof group[0]==='string'&&group[0].length>0);
    assert.ok(group.slice(1).every(value=>value===null||typeof value==='string'));
  }
  assert.ok(context.native_probe&&typeof context.native_probe==='object');
  if(context.old_day!==null)assert.match(context.old_day,/^\d{4}-\d{2}-\d{2}$/);
  for(const future of [context.native_probe,context.future_native].filter(Boolean)){assert.match(future.race_id,/^\d{8}-\d{2}-\d{2}$/);
    assert.ok(Number.isSafeInteger(future.index)&&future.index>=0&&future.index<32768);
    assert.ok(Number.isFinite(Date.parse(future.cutoff_at)));
  }
  validateSimulationExpected(context);
  return url.hash.split('.')[1];
}

function dateEvidence(context,results,p1Groups,lifecycleDay){
  const valid=day=>typeof day==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(day)&&
    Number.isFinite(Date.parse(day+'T00:00:00Z'))&&new Date(day+'T00:00:00Z').toISOString().slice(0,10)===day;
  const current=context.current_day??context.day;
  assert.ok(valid(context.day)&&valid(current)&&context.day<=current);
  if(lifecycleDay!==undefined)assert.equal(lifecycleDay,current,'lifecycle date changed during verification');
  const scope=context.day===current?'CURRENT_DAY':'HISTORICAL_DAY';
  if(context.date_scope!==undefined)assert.equal(context.date_scope,scope);
  assert.ok(Number.isSafeInteger(results)&&results>=0&&Number.isSafeInteger(p1Groups)&&p1Groups>=0);
  return {checked_day:context.day,current_day:current,date_scope:scope,
    checked_day_results:results,checked_day_p1_groups:p1Groups,
    current_day_results:scope==='CURRENT_DAY'?results:null,
    current_day_p1_groups:scope==='CURRENT_DAY'?p1Groups:null};
}

async function runChecked(context,{compactResults=false,probeRaceId=null,checkCurrentDay=false}={}){
  diagnosticPhase('context_validation');
  const key=validate(context),{chromium}=require('playwright');
  if(probeRaceId){assert.match(probeRaceId,/^\d{8}-\d{2}-\d{2}$/);assert.equal(probeRaceId.slice(0,8),context.day.replaceAll('-',''));}
  diagnosticPhase('browser_launch');
  const executablePath=['/usr/bin/google-chrome','/opt/google/chrome/google-chrome',
    '/opt/google/chrome/chrome','/usr/bin/chromium'].find(path=>fs.existsSync(path));
  assert.ok(executablePath,'installed browser required');
  const browser=await chromium.launch({headless:true,executablePath,args:['--no-sandbox']});
  let blocked=0,leaked=false,checked=0,futureVisible=false,nativeVisible=false,currentResults=0,p1Groups=0,rationaleViewsChecked=0,upcomingRowsChecked=0,venueResultsChecked=0,currentDayLifecycleViews=0,currentDayUpcomingRows=0,currentDayUpcomingCount=null,currentDayClosedCount=null,currentDayPendingCount=null,numericScenarios=0;
  try{
    diagnosticPhase('page_setup');
    const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[];
    page.setDefaultTimeout(45000);
    page.on('pageerror',error=>errors.push(error.name));
    page.on('request',request=>{if((request.url()+JSON.stringify(request.headers())).includes(key))leaked=true;});
    await page.route('**/*',route=>{
      const admission=requestAdmission(route.request(),key);
      if(admission.leaked)leaked=true;
      if(admission.allowed)return route.continue();
      blocked++;return route.abort('blockedbyclient');
    });
    diagnosticPhase('owner_navigation');await page.goto(context.owner_url,{waitUntil:'domcontentloaded'});
    let currentPresentation=false;
    for(let attempt=0;attempt<5;attempt++){
      diagnosticPhase('saved_view_load');
      if(attempt){await page.waitForTimeout(10000);await page.reload({waitUntil:'domcontentloaded'});}
      await page.waitForFunction(()=>document.querySelector('#file-message')?.textContent.includes('保存済み予想'),{},{timeout:90000});
      diagnosticPhase('presentation');
      const selection=await page.evaluate(()=>({ids:globalThis.RaceExistingModelCatalog?.models.map(m=>m.model_id),
        retired:globalThis.RaceExistingModelCatalog?.retired_model_ids || []}));
      currentPresentation=selection.ids?.length===15 && !selection.ids.includes('seller-shadow-v1-20261104')
        && selection.retired.includes('seller-shadow-v1-20261104');
      if(currentPresentation)break;
      // Only the exact known old presentation may wait for Pages deployment.
      assert.ok(selection.ids?.length===16 && selection.ids.includes('seller-shadow-v1-20261104')
        && selection.retired.length===0,'unexpected presentation selection');
    }
    assert.ok(currentPresentation,'retired seller still present in deployed assets');
    diagnosticPhase('feed_generation');
    await page.waitForFunction(expected=>Number(document.querySelector('#saved-view-sync')?.dataset.generation)>=expected,
      context.generation,{timeout:compactResults?360000:90000});
    async function selectDate(day){
      await page.locator('#selected-date').fill(day);await page.locator('#selected-date').dispatchEvent('change');
      await page.waitForFunction(expected=>{
        const status=document.querySelector('#saved-view-sync');
        if(status?.textContent.includes('の保存原本を読み込んでいます'))return false;
        if(!document.querySelector('#display-day')?.textContent.includes(expected))return false;
        return !status?.textContent.includes('保存履歴は日付を選んで表示できます')||status.dataset.historyDay===expected;
      },day,{timeout:90000});
    }
    for(const width of compactResults?[320,390,1440]:[390,1440]){
      diagnosticPhase('selected_day',width);
      await page.setViewportSize({width,height:1000});await selectDate(context.day);
      diagnosticPhase('race_lifecycle');
      await page.locator('[data-page="races"]').filter({visible:true}).first().click();
      if(await page.locator('#all-venues').isVisible())await page.locator('#all-venues').click();
      await page.locator('[data-race-view="upcoming"]').click();
      const upcoming=await page.locator('#all-races [data-cutoff-at]').evaluateAll(nodes=>nodes.map(n=>({at:Date.parse(n.dataset.cutoffAt),phase:n.dataset.racePhase})));
      for(const value of upcoming){assert.equal(value.phase,'upcoming');assert.ok(value.at>Date.now());}for(let i=1;i<upcoming.length;i++)assert.ok(upcoming[i-1].at<=upcoming[i].at);upcomingRowsChecked+=upcoming.length;
      if(context.day<context.current_day)assert.equal(upcoming.length,0);
      await page.locator('[data-race-view="results"]').click();
      if(context.minimum_results)assert.ok(await page.locator('#all-races .race-result-card').count()>0);
      if(await page.locator('#all-races .race-result-card').count()){
        diagnosticPhase('venue_results');
        const venue=await page.locator('#all-races .race-result-card').first().getAttribute('data-venue');
        await page.locator('#venue-buttons [data-venue]').filter({has:page.getByText(venue,{exact:true})}).first().click();
        assert.equal(await page.locator('#venue-filter').inputValue(),venue);
        assert.ok((await page.locator('#all-races .race-result-card').evaluateAll((nodes,v)=>nodes.every(n=>n.dataset.venue===v),venue)));
        await page.locator('[data-race-view="upcoming"]').click();assert.equal(await page.locator('#venue-filter').inputValue(),venue);
        await page.locator('[data-race-view="results"]').click();assert.equal(await page.locator('#venue-filter').inputValue(),venue);venueResultsChecked++;
        await page.locator('#all-venues').click();
      }
      diagnosticPhase('race_detail');
      if(!await page.locator('#page-races [data-open-race]').count())await page.locator('[data-race-view="upcoming"]').click();
      await page.locator('#page-races [data-open-race]').first().click();
      const grid=page.locator('#detail-tab-content .racer-grid[data-entrants]');
      assert.equal(await grid.count(),1);
      const entrants=Number(await grid.getAttribute('data-entrants'));
      assert.ok(entrants>=3&&entrants<=6);
      assert.equal(await page.locator('#detail-tab-content .placeholder-entrants').count(),0);
      const names=await grid.locator('.racer-name').allTextContents();
      assert.equal(names.length,entrants);
      for(const name of names){
        assert.ok(name.trim().length>0);
        assert.doesNotMatch(name,/(?:名前|出走者)\s*未取得|^\s*(?:選手\s*)?\d+\s*$/);
      }
      assert.ok(await page.locator('#prediction-select option').count()>=2);
      {
        diagnosticPhase('native_probe');
        const probe=context.future_native||context.native_probe;
        await page.locator('[data-page="races"]').filter({visible:true}).first().click();
        await page.locator('[data-race-view="'+(Date.now()<Date.parse(probe.cutoff_at)?'upcoming':'results')+'"]').click();
        const target=await revealRace(page,probe.race_id,context.day_races);await target.click();
        const selected=String(probe.index);
        assert.match(await page.locator('#prediction-select option[value="'+selected+'"]').innerText(),/^P1 /);
        await page.locator('#prediction-select').selectOption(selected);
        assert.equal(await page.locator('#detail-tab-content .forecast-panel').first().getAttribute('data-native-dispatch'),'true');
        nativeVisible=true;
        if(context.future_native&&!futureVisible){
          assert.ok(Date.now()<Date.parse(context.future_native.cutoff_at));futureVisible=true;
        }
      }
      if(compactResults){
        diagnosticPhase('compact_results');
        if(probeRaceId){await page.locator('[data-page="races"]').filter({visible:true}).first().click();await page.locator('[data-race-view="results"]').click();await (await revealRace(page,probeRaceId,context.day_races)).click();await page.locator('#prediction-select').selectOption('0');}
        assert.equal(await page.locator('.race-result-summary').isVisible(),true);
        if(probeRaceId)assert.match(await page.locator('.race-result-summary .saved-outcome').innerText(),/的中|不的中/);
        const normal=await page.locator('#race-detail').innerText();assert.doesNotMatch(normal,/SAVED FORECAST|PRIVATE_CYCLE|INDEPENDENT_RECEIPT|予想SHA/);
        assert.equal(await page.locator('#race-detail .forecast-panel').count(),1);assert.equal(await page.locator('#race-detail .race-audit-details').count(),0);
        const expectedRace=probeRaceId||(context.future_native||context.native_probe).race_id;
        const selected=await page.locator('#prediction-select').inputValue(),modelId=await page.locator('#race-detail .forecast-panel').getAttribute('data-model-id');
        const rationale=await page.locator('#race-detail .forecast-rationale').count()?await page.locator('#race-detail .forecast-rationale').innerText():null;
        diagnosticPhase('research_audit');
        await page.locator('[data-page="research"]').filter({visible:true}).first().click();
        const audit=page.locator('#research-race-audit');assert.equal(await audit.isVisible(),true);assert.equal(await page.locator('#research-race-select').inputValue(),expectedRace);assert.equal(await page.locator('#research-prediction-select').inputValue(),selected);
        assert.equal(await audit.locator('.race-audit-details').evaluate(n=>n.tagName),'SECTION');assert.equal(await audit.locator('.race-audit-details').getAttribute('data-model-id'),modelId);assert.match(await audit.innerText(),/予想SHA/);
        await audit.locator('[data-return-to-race]').click();assert.equal(await page.locator('#prediction-select').inputValue(),selected);
        assert.equal(await page.locator('#race-detail .forecast-rationale').count()?await page.locator('#race-detail .forecast-rationale').innerText():null,rationale);
        if(rationale){assert.equal(await page.locator('#race-detail .forecast-rationale-heading').innerText(),'予想根拠');rationaleViewsChecked++;}

      }
      diagnosticPhase('saved_result_metrics');
      assert.match(await page.locator('[data-page="results"]').filter({visible:true}).first().innerText(),/AI予想結果/);
      await page.locator('[data-page="results"]').filter({visible:true}).first().click();
      p1Groups=await page.locator('#results-model option').evaluateAll(options=>options.filter(o=>o.textContent.startsWith('P1 ')).length);
      assert.ok(p1Groups>=context.native_p1_groups);
      requireNativeGroups(context,await page.locator('#results-model option').evaluateAll(options=>options.map(option=>option.value)));
      const metrics=await page.locator('#saved-result-metrics').innerText();
      currentResults=Number(metrics.match(/取得結果\s*(\d+)レース/)?.[1]);
      assert.ok(currentResults>=context.minimum_results);
      for(const label of ['的中','不的中','保存Top8的中率','結果待ち'])assert.ok(metrics.includes(label));
      numericScenarios+=(await checkSimulationMetrics(page,context)).numeric_simulation_scenarios_checked;
      if(context.old_day){
        diagnosticPhase('historical_day');
        await selectDate(context.old_day);await page.locator('[data-page="results"]').filter({visible:true}).first().click();
        const old=Number((await page.locator('#saved-result-metrics').innerText()).match(/取得結果\s*(\d+)レース/)?.[1]);
        assert.ok(old>=context.old_completed);
      }
      if(checkCurrentDay){
        diagnosticPhase('current_day_lifecycle');
        await selectDate(context.current_day);
        await page.locator('[data-page="races"]').filter({visible:true}).first().click();
        if(await page.locator('#all-venues').isVisible())await page.locator('#all-venues').click();
        await page.locator('[data-race-view="upcoming"]').click();
        const visible=await page.locator('#all-races [data-cutoff-at]').evaluateAll(nodes=>nodes.map(n=>({at:Date.parse(n.dataset.cutoffAt),label:n.innerText})));
        for(const row of visible){assert.ok(row.at>Date.now());assert.doesNotMatch(row.label,/結果待ち/);}
        currentDayUpcomingRows+=visible.length;
        const count=async view=>Number((await page.locator('[data-race-view="'+view+'"]').innerText()).match(/（(\d+)）/)?.[1]);
        currentDayUpcomingCount=await count('upcoming');currentDayClosedCount=await count('results');
        assert.ok(Number.isSafeInteger(currentDayUpcomingCount)&&Number.isSafeInteger(currentDayClosedCount));
        if(currentDayUpcomingCount>0)assert.ok(visible.length>0);
        await page.locator('[data-page="results"]').filter({visible:true}).first().click();
        const metric=label=>page.locator('#saved-result-metrics .metric').filter({has:page.getByText(label,{exact:true})}).locator('strong');
        assert.equal(await metric('レース前').innerText(),currentDayUpcomingCount+'レース');
        currentDayPendingCount=Number((await metric('結果待ち').innerText()).match(/^(\d+)レース$/)?.[1]);
        assert.ok(Number.isSafeInteger(currentDayPendingCount)&&currentDayPendingCount<=currentDayClosedCount);
        if(!currentDayClosedCount){assert.equal(currentDayPendingCount,0);assert.equal(await page.locator('#saved-results-table .result-mobile-card').count(),0);}
        assert.equal(await page.locator('#saved-results-table .outcome-upcoming').count(),0);currentDayLifecycleViews++;
      }
      diagnosticPhase('viewport_overflow');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);checked++;
    }
    diagnosticPhase('final_integrity');
    assert.deepEqual(errors,[]);assert.equal(leaked,false);
    assert.equal((await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}))).includes(key),false);
    const numeric=validateSimulationExpected(context);assert.equal(numericScenarios,numeric?checked*4:0);
    diagnosticPhase('final_generation');diagnosticField('generation');
    if(numeric)assert.equal(Number(await page.locator('#saved-view-sync').getAttribute('data-generation')),numeric.generation);
    diagnosticPhase('final_day');
    const verifiedAt=new Date(),currentDay=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tokyo'}).format(verifiedAt);
    return {schema:'RACE_AI_LIVE_SITE_CHECK_COUNTS_V1',status:'LIVE_OWNER_SITE_VERIFIED',
      verified_at:verifiedAt.toISOString(),widths_checked:checked,
      feed_generation:Number(await page.locator('#saved-view-sync').getAttribute('data-generation')),
      ...dateEvidence({...context,current_day:currentDay,date_scope:undefined},currentResults,p1Groups,checkCurrentDay?context.current_day:undefined),
      lifecycle_checked_day:checkCurrentDay?context.current_day:null,
      selected_saved_day:context.day,current_day_lifecycle_views_checked:currentDayLifecycleViews,current_day_upcoming_rows_checked:currentDayUpcomingRows,current_day_upcoming_races:currentDayUpcomingCount,current_day_closed_races:currentDayClosedCount,current_day_pending_result_races:currentDayPendingCount,race_lifecycle_tabs_verified:true,upcoming_rows_checked:upcomingRowsChecked,venue_result_views_checked:venueResultsChecked,ai_results_navigation_verified:true,compact_result_ui_verified:compactResults,research_audit_verified:compactResults,available_rationale_preserved:compactResults,rationale_views_checked:rationaleViewsChecked,probe_result_matched:Boolean(compactResults&&probeRaceId),
      native_p1_groups_required:context.native_p1_groups,native_p1_detail_visible:nativeVisible,
      future_native_visible_before_cutoff:futureVisible,previous_day_checked:context.old_day!==null,
      active_model_families:15,removed_seller_hidden:true,
      participant_names:true,editable_daily_budget:true,per_race_1000_simulation:true,
      numeric_simulation_verified:numeric!==null,numeric_simulation_scenarios_checked:numericScenarios,
      numeric_budget_cap_exercised:numeric?.budget_cap_exercised??null,numeric_budget_cap_coverage:numeric?.budget_cap_coverage??'NOT_REQUESTED',
      hit_miss_rate_roi_and_settled_pending_net_visible:true,
      key_in_requests_or_storage:false,blocked_external_requests:blocked,official_source_requests:0,plaintext_published:false};
  }finally{try{await browser.close();}catch(error){diagnosticPhase('browser_cleanup');throw error;}}
}
async function run(context,options={}){return withDiagnostics(()=>runChecked(context,options));}

if(require.main===module){
  (async()=>run(JSON.parse(fs.readFileSync(process.argv[2],'utf8')),{compactResults:process.argv.includes('--compact-results'),checkCurrentDay:process.argv.includes('--check-current-day'),probeRaceId:process.argv.find(v=>v.startsWith('--race-id='))?.slice(10)||null}))()
    .then(report=>process.stdout.write(JSON.stringify(report)+'\n'))
    .catch(error=>{process.stdout.write(JSON.stringify(failureReport(error))+'\n');process.exitCode=2;});
}
module.exports={validate,dateEvidence,requestAdmission,revealRace,requireNativeGroups,validateSimulationExpected,requireSimulationGroup,requireSimulationSnapshot,readSimulationSnapshot,checkSimulationMetrics,withDiagnostics,failureReport,run};
