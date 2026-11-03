import test from 'node:test';
import assert from 'node:assert/strict';
import worker,{validDay,validRace} from '../workers/keirin_d1_oidc_worker.mjs';

test('strict calendar day and exact race identity',()=>{
  assert.equal(validDay('2026-11-03'),true);
  assert.equal(validDay('2026-02-30'),false);
  assert.equal(validDay('2026-11-3'),false);
  assert.equal(validRace({race_id:'202611033601',venue_code:36,race_no:1},'2026-11-03'),true);
  assert.equal(validRace({race_id:'202611033601',venue_code:36,race_no:2},'2026-11-03'),false);
  assert.equal(validRace({race_id:'202611033601',venue_code:36,race_no:1,admin:true},'2026-11-03'),false);
});

test('health returns metadata only, never database data',async()=>{
  const response=await worker.fetch(new Request('https://worker.example/health'),{});
  assert.equal(response.status,200);
  const body=await response.json();
  assert.deepEqual(Object.keys(body).sort(),['service','state']);
  assert.equal(response.headers.get('cache-control'),'no-store');
});
test('all data routes refuse unauthenticated requests',async()=>{
  for(const [method,path] of [
    ['GET','/v1/status?day=2026-11-03'],
    ['POST','/v1/cohort'],
  ]){
    const request=new Request('https://worker.example'+path,{method});
    const result=await worker.fetch(request,{});
    assert.equal(result.status,401);
    assert.deepEqual(await result.json(),{error:'UNAUTHORIZED'});
  }
});
test('malformed fake token never produces private state',async()=>{
  const request=new Request('https://worker.example/v1/status?day=2026-11-03',{
    headers:{authorization:'Bearer aaa.bbb.ccc'},
  });
  const response=await worker.fetch(request,{});
  assert.equal(response.status,401);
  assert.deepEqual(await response.json(),{error:'UNAUTHORIZED'});
});
test('unknown endpoint does not reveal data or fetch GitHub keys',async()=>{
  const request=new Request('https://worker.example/forecast-original');
  const response=await worker.fetch(request,{});
  assert.equal(response.status,404);
});
