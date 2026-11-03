import test from 'node:test';
import assert from 'node:assert/strict';
import {randomBytes} from 'node:crypto';
import {mkdtempSync,readFileSync,symlinkSync,statSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {seal,unseal,writeOnce,readKey,syntheticKey,CheckpointError} from '../scripts/keirin_github_checkpoint.mjs';
const scope={schema:'RACE_AI_GITHUB_SQLITE_V1',repository_id:'1416489937',mode:'production',generation:1,previous_cipher_sha256:null};
const bytes=Buffer.concat([Buffer.from('SQLite format 3\0'),Buffer.alloc(512,7)]);
const key=()=>randomBytes(32);
const temp=()=>mkdtempSync(join(tmpdir(),'keirin-checkpoint-'));

test('authenticated snapshot round-trip preserves exact bytes',()=>{
 const k=key(), sealed=seal(bytes,k,scope);
 assert.deepEqual(unseal(sealed,k,scope),bytes);
 assert.equal(sealed.includes(bytes),false);
 assert.ok(sealed.length<4096);
});
test('each seal uses a fresh random nonce',()=>{
 const k=key(); assert.notDeepEqual(seal(bytes,k,scope),seal(bytes,k,scope));
});
test('wrong key never opens a checkpoint',()=>{
 assert.throws(()=>unseal(seal(bytes,key(),scope),key(),scope),CheckpointError);
});
test('ciphertext tampering is rejected',()=>{
 const k=key(), blob=JSON.parse(seal(bytes,k,scope));
 const raw=Buffer.from(blob.ciphertext,'base64');raw[7]^=1;blob.ciphertext=raw.toString('base64');
 assert.throws(()=>unseal(Buffer.from(JSON.stringify(blob)),k,scope),CheckpointError);
});
test('header tampering is authenticated and exact scope required',()=>{
 const k=key(), original=seal(bytes,k,scope), obj=JSON.parse(original);
 obj.header.generation=2;
 assert.throws(()=>unseal(Buffer.from(JSON.stringify(obj)),k,{...scope,generation:2}),CheckpointError);
 assert.throws(()=>unseal(original,k,{...scope,repository_id:'other'}),CheckpointError);
});
test('different history or production/test scope cannot be substituted',()=>{
 const k=key(), original=seal(bytes,k,scope);
 assert.throws(()=>unseal(original,k,{...scope,generation:2,previous_cipher_sha256:'a'.repeat(64)}),CheckpointError);
 assert.throws(()=>unseal(original,k,{...scope,mode:'synthetic'}),CheckpointError);
});
test('only full random-sized key accepted; fixture key prohibited for production',()=>{
 assert.throws(()=>readKey(undefined,'production'),CheckpointError);
 assert.throws(()=>readKey('aaa','production'),CheckpointError);
 assert.throws(()=>readKey(Buffer.alloc(32).toString('base64'),'production'),CheckpointError);
 assert.throws(()=>readKey(syntheticKey().toString('base64'),'production'),CheckpointError);
 const k=key();assert.deepEqual(readKey(k.toString('base64'),'production'),k);
});
test('scope, generations, sizes and SQLite identity validated',()=>{
 assert.throws(()=>seal(Buffer.from('secret'),key(),scope),CheckpointError);
 assert.throws(()=>seal(bytes,key(),{...scope,generation:0}),CheckpointError);
 assert.throws(()=>seal(bytes,key(),{...scope,generation:2}),CheckpointError);
 assert.throws(()=>seal(bytes,key(),{...scope,extra:'secret'}),CheckpointError);
 assert.throws(()=>seal(Buffer.alloc(8*1024*1024+1),key(),scope),CheckpointError);
});
test('create-only private output; never overwrite or follow symlink',()=>{
 const root=temp();try{
  const file=join(root,'state.enc');writeOnce(file,Buffer.from('ciphertext'));
  assert.equal(statSync(file).mode&0o777,0o600);
  assert.throws(()=>writeOnce(file,Buffer.from('replacement')),CheckpointError);
  assert.equal(readFileSync(file).toString(),'ciphertext');
  symlinkSync(file,join(root,'link'));assert.throws(()=>writeOnce(join(root,'link'),Buffer.from('x')),CheckpointError);
 }finally{rmSync(root,{recursive:true,force:true});}
});
test('malformed and unexpected envelope fields rejected',()=>{
 const k=key(), b=JSON.parse(seal(bytes,k,scope));
 assert.throws(()=>unseal(Buffer.from('{bad'),k,scope),CheckpointError);
 b.plaintext='never accept';assert.throws(()=>unseal(Buffer.from(JSON.stringify(b)),k,scope),CheckpointError);
});
