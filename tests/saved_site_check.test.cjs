'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const C=require('../scripts/boat_saved_site_check.cjs');
const key='fixture-viewer-key';
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
