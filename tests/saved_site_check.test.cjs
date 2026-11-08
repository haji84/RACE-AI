'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const C=require('../scripts/boat_saved_site_check.cjs');
const key='fixture-viewer-key';
test('historical checks report their selected day without claiming current-day results',()=>{
  const historical=C.dateEvidence({day:'2030-04-01',current_day:'2030-04-02'},98,30);
  assert.equal(historical.date_scope,'HISTORICAL_DAY');assert.equal(historical.checked_day_results,98);
  assert.equal(historical.current_day_results,null);assert.equal(historical.current_day_p1_groups,null);
  const current=C.dateEvidence({day:'2030-04-02',current_day:'2030-04-02'},3,2);
  assert.equal(current.date_scope,'CURRENT_DAY');assert.equal(current.current_day_results,3);
});
test('a midnight rollover refuses to relabel the lifecycle counts for the prior day',()=>{
  const before={day:'2030-04-01',current_day:'2030-04-01'};
  assert.equal(C.dateEvidence(before,129,57,'2030-04-01').current_day_results,129);
  const after={day:'2030-04-01',current_day:'2030-04-02'};
  assert.throws(()=>C.dateEvidence(after,129,57,'2030-04-01'));
  assert.equal(C.dateEvidence(after,129,57).current_day_results,null);
});
const request=(url='https://raw.githubusercontent.com/haji84/RACE-AI/example/latest.json',
  {headers={},method='GET',body=null}={})=>({url:()=>url,headers:()=>headers,method:()=>method,postData:()=>body});

test('key-bearing URLs, headers and bodies are rejected before request continuation',()=>{
  assert.deepEqual(C.requestAdmission(request(),key),{allowed:true,leaked:false});
  for(const value of [
    request('https://api.github.com/repos/haji84/RACE-AI?key='+key),
    request(undefined,{headers:{authorization:key}}),
    request(undefined,{method:'POST',body:JSON.stringify({key})})
  ])assert.deepEqual(C.requestAdmission(value,key),{allowed:false,leaked:true});
});

test('non-read methods, bodies and other hosts never leave the browser',()=>{
  for(const value of [
    request(undefined,{method:'POST'}),
    request(undefined,{body:'unrelated-body'}),
    request('https://example.invalid/'),
    request('http://api.github.com/')
  ])assert.equal(C.requestAdmission(value,key).allowed,false);
  assert.equal(C.requestAdmission(request(undefined,{method:'HEAD'}),key).allowed,true);
});

function fakePage(total,targetPosition){
  let visible=Math.min(60,total),clicks=0;
  const target={count:async()=>targetPosition<=visible?1:0};
  return {
    locator:selector=>{assert.match(selector,/data-open-race/);return target;},
    getByRole:(role,options)=>{
      assert.equal(role,'button');assert.ok(options.name.test('さらに60件表示'));
      return {isVisible:async()=>visible<total,click:async()=>{visible=Math.min(total,visible+60);clicks++;}};
    },
    clicks:()=>clicks
  };
}

test('a genuine race after the first 120 cards is reached through bounded UI pagination',async()=>{
  const page=fakePage(132,132);
  await C.revealRace(page,'20300401-01-12',132);
  assert.equal(page.clicks(),2);
});

test('an absent race cannot cause unbounded paging or invented availability',async()=>{
  const page=fakePage(132,133);
  await assert.rejects(C.revealRace(page,'20300401-01-12',132));
  assert.equal(page.clicks(),2);
  await assert.rejects(C.revealRace(page,'20300401-01-12',0));
});

test('extra unrelated P1 groups cannot mask a missing native model or version',()=>{
  const context={native_groups:[['native-one','v1',null,null],['native-two','v2',null,null]]};
  const option=(model,version)=>JSON.stringify(['research','boat','P1',model,version,null]);
  assert.throws(()=>C.requireNativeGroups(context,[option('native-one','v1'),option('unrelated','v2')]));
  assert.throws(()=>C.requireNativeGroups(context,[option('native-one','v1'),option('native-two','v1')]));
  assert.doesNotThrow(()=>C.requireNativeGroups(context,['',option('native-one','v1'),option('native-two','v2')]));
});

test('unknown-version native groups bind their saved code identity',()=>{
  const context={native_groups:[['native-one',null,null,'a'.repeat(40)]]};
  const option=code=>JSON.stringify(['research','boat','P1','native-one',null,null,code]);
  assert.throws(()=>C.requireNativeGroups(context,[option('b'.repeat(40))]));
  assert.doesNotThrow(()=>C.requireNativeGroups(context,[option('a'.repeat(40))]));
});

const crypto=require('node:crypto'),fs=require('node:fs');
const numericGroup=JSON.stringify(['research','boat','P1','invented-numeric','v1',null]);
const hash=value=>crypto.createHash('sha256').update(value).digest('hex');
const overall={races:14,available:13,hits:3,misses:8,pending:1,void:2,noForecast:0,review:0};
const totals=[
  {budgetPerDay:10000,raceBudget:800,spent:9600,reserved:9600,held:0,unspent:400,payout:5000,refund:1700,settledStake:8000,settledCount:10,pendingStake:1600,bought:12,skippedBudget:2,balance:7100,settledNet:-1300,net:null,roi:83.75,boughtComparison:{hits:3,misses:6,pending:1,void:2,noForecast:0,review:0}},
  {budgetPerDay:10000,raceBudget:1000,spent:10000,reserved:10000,held:0,unspent:0,payout:10000,refund:2200,settledStake:8000,settledCount:8,pendingStake:2000,bought:10,skippedBudget:4,balance:12200,settledNet:4200,net:null,roi:152.5,boughtComparison:{hits:3,misses:4,pending:1,void:2,noForecast:0,review:0}},
  {budgetPerDay:5000,raceBudget:800,spent:4800,reserved:4800,held:0,unspent:200,payout:2500,refund:1600,settledStake:3200,settledCount:4,pendingStake:1600,bought:6,skippedBudget:8,balance:4300,settledNet:900,net:null,roi:128.125,boughtComparison:{hits:2,misses:1,pending:1,void:2,noForecast:0,review:0}},
  {budgetPerDay:5000,raceBudget:1000,spent:5000,reserved:5000,held:0,unspent:0,payout:5000,refund:1000,settledStake:3000,settledCount:3,pendingStake:2000,bought:5,skippedBudget:9,balance:6000,settledNet:3000,net:null,roi:200,boughtComparison:{hits:2,misses:1,pending:1,void:1,noForecast:0,review:0}}
];
function financialContext(){
  return {schema:'RACE_AI_PRIVATE_LIVE_SITE_CHECK_CONTEXT_V1',owner_url:'https://haji84.github.io/RACE-AI/#saved='+'a'.repeat(64)+'.'+'e'.repeat(43),
    day:'2030-04-01',current_day:'2030-04-01',generation:12,day_races:14,minimum_results:13,native_p1_groups:1,
    native_groups:[['invented-numeric','v1',null,null]],native_probe:{race_id:'20300401-01-01',index:0,cutoff_at:'2030-04-01T12:00:00+09:00'},future_native:null,old_day:null,old_completed:0,
    numeric_simulation_required:true,simulation_as_of:'2030-04-01T15:00:00+09:00',simulation_expected:{schema:'RACE_AI_SAVED_SITE_SIMULATION_EXPECTED_V1',day:'2030-04-01',generation:12,
      group_sha256:hash(numericGroup),eligible_native_races:14,issued_races:14,observed:structuredClone(overall),observed_closed:structuredClone(overall),
      lifecycle:{as_of:'2030-04-01T15:00:00+09:00',closed:14,upcoming:0,unknown:0},budget_cap_exercised:true,budget_cap_coverage:'EXERCISED',
      scenarios:totals.map(s=>({...structuredClone(s),budgetTotal:s.budgetPerDay,comparison:{hits:3,misses:8,pending:1,void:2,noForecast:0,review:0}}))}};
}
const yen=n=>n.toLocaleString('ja-JP')+'円';
const net=n=>n===null?'未確定':(n>0?'＋':'')+yen(n);
const rate=c=>c.hits+c.misses?(c.hits/(c.hits+c.misses)*100).toFixed(1)+'%':'算出対象なし';
function numericSnapshot(context=financialContext(),daily=10000,race=800,{closed=false}={}){
  const expected=context.simulation_expected,s=expected.scenarios.find(s=>s.budgetPerDay===daily&&s.raceBudget===race),c=closed?expected.observed_closed:expected.observed;
  const metric=(label,value,detail='')=>({label,value,detail});
  const saved=[...Object.entries({'取得結果':'available','的中':'hits','不的中':'misses','結果待ち':'pending','中止・返還':'void','照合保留':'review'}).map(([label,key])=>metric(label,c[key]+'レース')),
    metric('保存Top8的中率',rate(c),c.hits+' / '+(c.hits+c.misses)+'レース（結果待ち・照合不可等を除外）')];
  if(closed){saved.push(metric('レース前',expected.lifecycle.upcoming+'レース'));if(expected.lifecycle.unknown)saved.push(metric('締切未確認',expected.lifecycle.unknown+'レース'));}
  return {day:context.day,generation:context.generation,group_sha256:expected.group_sha256,daily_budget:daily,race_budget:race,
    coverage:'対象 '+expected.observed.races+'レース · 結果対象 '+expected.lifecycle.closed+' · 未予想・照合不可 '+(c.noForecast+c.review),saved_metrics:saved,
    simulation_metrics:[metric('予定購入額',yen(s.spent),s.bought+'レース · 上限'+yen(race)+'/レース · 実購入なし'),
      metric('未使用予算',yen(s.unspent),'1日 '+yen(daily)+' × 1日 · 追加未配分 '+yen(s.held)),
      metric('確認済み払戻',yen(s.payout),'返還 '+yen(s.refund)),metric('確定分の収支',net(s.settledNet),'購入額 '+yen(s.settledStake)+' の分だけ'),
      metric('未確定購入額',yen(s.pendingStake)),metric('全体の収支',net(s.net),'仮の残高 '+yen(s.balance)),
      metric('確定分の回収率',s.roi===null?'未確定':s.roi.toFixed(1)+'%'),metric('収支確定の購入予定',s.settledCount+' / '+s.bought+'レース'),
      metric('購入予定分の的中率',rate(s.boughtComparison),s.boughtComparison.hits+' / '+(s.boughtComparison.hits+s.boughtComparison.misses)+'レース（結果待ち等を除外）')]};
}
function requireNumeric(context,snapshot,daily=10000,race=800){
  assert.equal(typeof C.requireSimulationSnapshot,'function','numeric DOM acceptance is available');
  return C.requireSimulationSnapshot(context,snapshot,daily,race);
}
test('numeric contexts require exact binding, four unique scenarios and explicit required admission while legacy contexts keep their guards',()=>{
  const context=financialContext();assert.doesNotThrow(()=>C.validate(context));
  const legacy=structuredClone(context);delete legacy.simulation_expected;delete legacy.numeric_simulation_required;delete legacy.simulation_as_of;
  assert.doesNotThrow(()=>C.validate(legacy));assert.throws(()=>C.validate({...legacy,owner_url:'https://example.invalid/'}));
  for(const edit of [
    c=>delete c.simulation_expected,c=>delete c.numeric_simulation_required,c=>c.numeric_simulation_required=false,
    c=>c.simulation_expected.generation--,c=>c.simulation_expected.day='2030-04-02',
    c=>c.simulation_expected.scenarios.pop(),c=>c.simulation_expected.scenarios[1]=structuredClone(c.simulation_expected.scenarios[0]),
    c=>c.simulation_expected.scenarios[0].refund=true,c=>c.simulation_expected.scenarios[0].roi=NaN,
    c=>c.simulation_expected.observed.races=13,c=>c.simulation_expected.lifecycle.closed=13,
    c=>c.simulation_expected.private_picks=['PRIVATE-PICKS']
  ]){const wrong=structuredClone(context);edit(wrong);assert.throws(()=>C.validate(wrong));}
});
test('numeric model selection binds the exact native model/version and rejects duplicate or unrelated options',()=>{
  assert.equal(typeof C.requireSimulationGroup,'function');const context=financialContext();
  assert.equal(C.requireSimulationGroup(context,['',numericGroup]),numericGroup);
  assert.throws(()=>C.requireSimulationGroup(context,[]));assert.throws(()=>C.requireSimulationGroup(context,[numericGroup,numericGroup]));
  const unrelated=JSON.stringify(['research','boat','P1','unrelated','v1',null]);context.simulation_expected.group_sha256=hash(unrelated);
  assert.throws(()=>C.requireSimulationGroup(context,[unrelated]));
});
test('all four literal numeric scenarios accept exact money, percentages, hit denominators and pending net',()=>{
  const context=financialContext();for(const s of totals)assert.doesNotThrow(()=>requireNumeric(context,numericSnapshot(context,s.budgetPerDay,s.raceBudget),s.budgetPerDay,s.raceBudget));
});
test('changing the budget input without recalculating financial totals is rejected',()=>{
  const context=financialContext(),stale=numericSnapshot(context);stale.daily_budget=5000;
  assert.throws(()=>requireNumeric(context,stale,5000,800));
  assert.throws(()=>requireNumeric(context,numericSnapshot(context),5000,800));
});
test('wrong payout, refund, pending stake, denominator, rounded ROI or null net is rejected',()=>{
  const context=financialContext();
  for(const [label,field,value] of [['確認済み払戻','value','5,001円'],['確認済み払戻','detail','返還 1,701円'],['未確定購入額','value','1,599円'],
    ['購入予定分の的中率','detail','3 / 8レース'],['確定分の回収率','value','83.7%'],['全体の収支','value','0円']]){
    const wrong=numericSnapshot(context);wrong.simulation_metrics.find(m=>m.label===label)[field]=value;
    assert.throws(()=>requireNumeric(context,wrong),label);
  }
  const denominator=numericSnapshot(context);denominator.saved_metrics.find(m=>m.label==='保存Top8的中率').detail='3 / 10レース';
  assert.throws(()=>requireNumeric(context,denominator));
});
test('stale day, feed generation or selected model cannot satisfy the numeric gate',()=>{
  const context=financialContext();for(const [field,value] of [['day','2030-03-31'],['generation',13],['group_sha256','b'.repeat(64)],['race_budget',1000]]){
    const wrong=numericSnapshot(context);wrong[field]=value;assert.throws(()=>requireNumeric(context,wrong));
  }
});
test('closed-result presentation uses the closed summary and rejects an unreflected cutoff crossing',()=>{
  const context=financialContext(),expected=context.simulation_expected;
  expected.lifecycle={as_of:context.simulation_as_of,closed:13,upcoming:1,unknown:0};
  expected.observed_closed={...overall,races:13,pending:0};
  assert.doesNotThrow(()=>requireNumeric(context,numericSnapshot(context,10000,800,{closed:true})));
  const stale=numericSnapshot(context,10000,800,{closed:true});stale.saved_metrics.find(m=>m.label==='レース前').value='0レース';
  assert.throws(()=>requireNumeric(context,stale));
});

let chromium;try{({chromium}=require('playwright'));}catch{}
const executablePath=[process.env.CHROMIUM_PATH,'/usr/bin/chromium','/usr/bin/google-chrome'].find(p=>p&&fs.existsSync(p));
test('actual DOM budget changes must recalculate all four scenarios; stale money and refunds fail',{skip:!chromium||!executablePath},async()=>{
  assert.equal(typeof C.checkSimulationMetrics,'function','the browser drives numeric financial acceptance');
  const browser=await chromium.launch({headless:true,executablePath,args:['--no-sandbox']});
  try{
    const page=await browser.newPage(),context=financialContext();
    await page.setContent('<div id="saved-view-sync" data-generation="12"></div><input id="selected-date" value="2030-04-01"><select id="results-model"></select><input id="simulation-budget" value="10000"><select id="simulation-race-budget"><option>800</option><option>1000</option></select><div id="result-coverage"></div><div id="saved-result-metrics"></div><div id="simulation-metrics"></div>');
    const snapshots=Object.fromEntries(totals.map(s=>[s.budgetPerDay+':'+s.raceBudget,numericSnapshot(context,s.budgetPerDay,s.raceBudget)]));
    await page.evaluate(({group,snapshots})=>{
      document.querySelector('#results-model').append(new Option('Native P1',group));
      window.numericSnapshots=snapshots;window.staleBudget=false;window.wrongRefund=false;
      const render=()=>{
        const daily=document.querySelector('#simulation-budget').value,race=document.querySelector('#simulation-race-budget').value;
        const snapshot=snapshots[(window.staleBudget?'10000':daily)+':'+race];
        document.querySelector('#result-coverage').textContent=snapshot.coverage;
        for(const [id,values] of [['saved-result-metrics',snapshot.saved_metrics],['simulation-metrics',snapshot.simulation_metrics]]){
          const root=document.querySelector('#'+id);root.replaceChildren();
          for(const value of values){const card=document.createElement('article');card.className='metric';for(const [tag,name,text] of [['span','metric-label',value.label],['strong','',value.value],['small','',window.wrongRefund&&value.label==='確認済み払戻'?'返還 999円':value.detail]]){const n=document.createElement(tag);n.className=name;n.textContent=text;card.append(n);}root.append(card);}
        }
      };
      for(const id of ['simulation-budget','simulation-race-budget','results-model'])document.querySelector('#'+id).addEventListener('change',render);
      render();
    },{group:numericGroup,snapshots});
    const result=await C.checkSimulationMetrics(page,context);assert.equal(result.numeric_simulation_verified,true);assert.equal(result.numeric_simulation_scenarios_checked,4);
    await page.evaluate(()=>window.staleBudget=true);await assert.rejects(C.checkSimulationMetrics(page,context));
    await page.evaluate(()=>{window.staleBudget=false;window.wrongRefund=true;});await assert.rejects(C.checkSimulationMetrics(page,context));
    await page.evaluate(()=>window.wrongRefund=false);
    const legacy=structuredClone(context);delete legacy.simulation_expected;delete legacy.numeric_simulation_required;
    assert.equal((await C.checkSimulationMetrics(page,legacy)).numeric_simulation_verified,false);
  }finally{await browser.close();}
});
