import test from 'node:test';
import assert from 'node:assert/strict';
import worker,{trustedJwks,keyAgeValid} from '../workers/keirin_d1_oidc_worker.mjs';

const pub={kid:'github-public-rsa-1',kty:'RSA',alg:'RS256',use:'sig',
           n:'q'.repeat(342),e:'AQAB'};

test('public RSA JWK shape rejects malformed or mixed trust roots',()=>{
  assert.equal(trustedJwks([pub]),true);
  assert.equal(trustedJwks([pub,pub]),false);
  assert.equal(trustedJwks([]),false);
  assert.equal(trustedJwks([{...pub,e:'Aw'}]),false);
  assert.equal(trustedJwks([{...pub,use:'enc'}]),false);
  assert.equal(trustedJwks([{...pub,n:'short'}]),false);
  assert.equal(trustedJwks([{...pub,kty:'EC'}]),false);
});
test('signed public key snapshots expire after bounded window',()=>{
  const now=Date.parse('2026-11-03T07:00:00Z');
  assert.equal(keyAgeValid('2026-11-03T06:30:00Z',now),true);
  assert.equal(keyAgeValid('2026-10-20T06:30:00Z',now),false);
  assert.equal(keyAgeValid('2026-11-04T06:30:00Z',now),false);
  assert.equal(keyAgeValid('nonsense',now),false);
  assert.equal(keyAgeValid('2026-11-03T06:50:00Z',now,2*3600000),true);
});
test('refresh never accepts an anonymous caller',async()=>{
  const resp=await worker.fetch(new Request(
      'https://example.test/v1/jwks-refresh',{
        method:'POST',body:JSON.stringify({keys:[pub]})
      }),{});
  assert.equal(resp.status,401);
  assert.equal((await resp.json()).error,'UNAUTHORIZED');
});
test('refresh requires signed token and cannot leak any stored JWK',async()=>{
  const resp=await worker.fetch(new Request(
      'https://example.test/v1/jwks-refresh',{
        method:'POST',
        headers:{authorization:'Bearer a.b.c'},
        body:JSON.stringify({keys:[pub]})
      }),{});
  assert.equal(resp.status,401);
  assert.equal((await resp.json()).error,'UNAUTHORIZED');
});
