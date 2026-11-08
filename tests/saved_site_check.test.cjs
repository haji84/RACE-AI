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
