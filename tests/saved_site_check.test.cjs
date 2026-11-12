'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const C=require('../scripts/boat_saved_site_check.cjs');
const key='fixture-viewer-key';
test('private browser failures identify only checker lines and safe error kinds',()=>{
  const error=new Error('private URL, key, model and tickets must never be logged');
  error.name='TimeoutError';
  error.stack='TimeoutError: private contents\n    at run (/runner/scripts/boat_saved_site_check.cjs:157:91)\n    at https://private.invalid/secret:4:8';
  assert.deepEqual(C.browserFailure(error),{status:'LIVE_OWNER_SITE_REJECTED',reason:'SAVED_SITE_BROWSER_CHECK_FAILED',error_kind:'TimeoutError',checker_line:157,checker_column:91});
  assert.deepEqual(C.browserFailure({name:'private-secret',stack:'private-secret'}),{status:'LIVE_OWNER_SITE_REJECTED',reason:'SAVED_SITE_BROWSER_CHECK_FAILED',error_kind:'Error',checker_line:null,checker_column:null});
});
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

const tickets=[[1,2,3],[2,1,3]];
const ticketSha=require('node:crypto').createHash('sha256').update(JSON.stringify(tickets)).digest('hex');
function stageContext(stage){
  return {schema:'RACE_AI_PRIVATE_LIVE_SITE_CHECK_CONTEXT_V1',
    owner_url:'https://haji84.github.io/RACE-AI/#saved='+'a'.repeat(64)+'.'+'b'.repeat(43),
    day:'2030-04-01',current_day:'2030-04-01',generation:1,minimum_results:0,
    old_completed:0,old_day:null,day_races:1,stage,native_group_count:1,
    ['native_'+stage.toLowerCase()+'_groups']:1,native_groups:[['native-one','v1',null,null]],
    native_probe:{race_id:'20300401-01-01',index:0,cutoff_at:'2030-04-01T02:00:00Z',
      stage,...(stage==='P0'?{model_id:'native-one',tickets_sha256:ticketSha,
        artifact_id:42,original_json_sha256:'e'.repeat(64),prediction_sha256:'d'.repeat(64),
        model_sha256:'d'.repeat(64),source_code_commit:'a'.repeat(40)}:{})},future_native:null};
}

test('explicit P0 context validates while cross-stage labels and counts are rejected',()=>{
  const p0=stageContext('P0');assert.doesNotThrow(()=>C.validate(p0));
  const p1=stageContext('P1');assert.doesNotThrow(()=>C.validate(p1));
  const legacy=structuredClone(p1);delete legacy.stage;delete legacy.native_group_count;delete legacy.native_probe.stage;
  assert.doesNotThrow(()=>C.validate(legacy));
  for(const changed of [
    {...p0,native_p1_groups:1},
    {...p1,native_p0_groups:1},
    {...p0,stage:'P2'},
    {...p0,native_probe:{...p0.native_probe,stage:'P1'}},
    {...p0,native_probe:{...p0.native_probe,tickets_sha256:null}}
  ])assert.throws(()=>C.validate(changed));
});

test('P0 groups require their own stage and cannot be supplied by identical P1 model groups',()=>{
  const p0=stageContext('P0');
  const option=stage=>JSON.stringify(['research','boat',stage,'native-one','v1',null]);
  assert.throws(()=>C.requireNativeGroups(p0,[option('P1')]));
  assert.doesNotThrow(()=>C.requireNativeGroups(p0,[option('P0')]));
  assert.throws(()=>C.requireNativeGroups(stageContext('P1'),[option('P0')]));
});

test('P0 result counts stay P0 for current and historical days',()=>{
  const p0=stageContext('P0');
  const current=C.dateEvidence(p0,14,2);
  assert.equal(current.stage,'P0');assert.equal(current.checked_day_native_groups,2);
  assert.equal(current.checked_day_p0_groups,2);assert.equal(current.current_day_p0_groups,2);
  assert.equal(Object.hasOwn(current,'checked_day_p1_groups'),false);
  assert.equal(Object.hasOwn(current,'current_day_p1_groups'),false);
  const historical=C.dateEvidence({...p0,current_day:'2030-04-02'},14,2);
  assert.equal(historical.current_day_native_groups,null);assert.equal(historical.current_day_p0_groups,null);
});

test('native P0 detail binds its stage model and exact saved tickets without a P1 dispatcher claim',()=>{
  const context=stageContext('P0'),probe=context.native_probe;
  const detail={label:'P0 · native-one',modelId:'native-one',nativeDispatch:'false',tickets};
  assert.doesNotThrow(()=>C.requireNativeDetail(context,probe,detail));
  for(const changed of [
    {...detail,label:'P1 · native-one'}, {...detail,modelId:'native-other'},
    {...detail,nativeDispatch:'true'}, {...detail,tickets:[[3,1,2]]}
  ])assert.throws(()=>C.requireNativeDetail(context,probe,changed));
  assert.doesNotThrow(()=>C.requireNativeDetail(stageContext('P1'),stageContext('P1').native_probe,
    {label:'P1 · native-one',nativeDispatch:'true'}));
});

test('P0 research audit binds the original receipt even when another original has identical tickets',()=>{
  const context=stageContext('P0'),probe=context.native_probe;
  const fields=[['原本artifact ID','42'],['原本JSON SHA',probe.original_json_sha256],
    ['予想SHA',probe.prediction_sha256],['モデル / 学習物SHA',probe.model_sha256],
    ['保存コードのコミット',probe.source_code_commit]];
  const audit={stage:'P0',modelId:probe.model_id,fields};
  assert.doesNotThrow(()=>C.requireNativeAudit(context,probe,audit));
  for(let i=0;i<fields.length;i++){
    const altered=fields.map(pair=>[...pair]);altered[i][1]='different-original';
    assert.throws(()=>C.requireNativeAudit(context,probe,{...audit,fields:altered}));
  }
  assert.throws(()=>C.requireNativeAudit(context,probe,{...audit,stage:'P1'}));
});

test('a different authenticated same-day original cannot replace the expected reconciliation receipt',()=>{
  const context=stageContext('P0'),probe=context.native_probe;
  context.expected_original={original_id:probe.artifact_id,json_sha256:probe.original_json_sha256,
    source_sha:probe.source_code_commit,day_jst:context.day};
  assert.doesNotThrow(()=>C.validate(context));
  for(const [field,value] of [['original_id',43],['json_sha256','f'.repeat(64)],
    ['source_sha','b'.repeat(40)],['day_jst','2030-04-02']]){
    assert.throws(()=>C.validate({...context,expected_original:{...context.expected_original,[field]:value}}));
  }
});
