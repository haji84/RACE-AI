import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {existsSync, mkdtempSync, readFileSync, rmSync,writeFileSync,mkdirSync,linkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {DatabaseSync} from 'node:sqlite';
import {spawn} from 'node:child_process';
import {setTimeout as delay} from 'node:timers/promises';

const moduleUrl=new URL('../workers/private_wire_vault.mjs',import.meta.url);
const digest=value=>createHash('sha256').update(value).digest('hex');
const CHUNK=524288;
function claim(wire, overrides={}){
  return {schema:'RACE_AI_LOCAL_PRIVATE_WIRE_CLAIM_V1',destination_contract:'LOCAL_SQLITE_D1_BATCH_CANDIDATE_V1',
    destination_ref:'local-private-vault-fixture',owner_ref:'fictional-local-owner',request_sha256:'a'.repeat(64),
    wire_sha256:digest(wire),delivery_sha256:'b'.repeat(64),model_source_sha40:'d'.repeat(40),
    retention_request_sha256:'c'.repeat(64),reservation_sha256:'e'.repeat(64),reservation_row_sha256:'f'.repeat(64),
    reservation_commit_guard_at:'2030-01-15T00:16:00.123456Z',retain_until:'2030-02-15T00:00:00+00:00',
    protection_policy:'LOCAL_INSERT_ONLY_SQL_V1',wire_bytes:wire.length,
    chunk_sha256:Array.from({length:Math.ceil(wire.length/CHUNK)},(_,i)=>digest(wire.subarray(i*CHUNK,(i+1)*CHUNK))),...overrides};
}
async function modules(){
  assert.ok(existsSync(fileURLToPath(moduleUrl)),'durable local whole-wire vault is missing');
  return {...await import(moduleUrl),...await import('./support/local_private_wire_d1.mjs')};
}
function folder(t){
  const dir=mkdtempSync(path.join(tmpdir(),'race34-fictional-'));
  t.after(()=>rmSync(dir,{recursive:true,force:true}));
  return dir;
}
if(process.argv[2]==='--vault-worker'){
  await worker(...process.argv.slice(3));
  process.exit(0);
}

test('original opaque bytes survive a durable create, close and read',async t=>{
  const {createLocalPrivateWire,readLocalPrivateWire,openLocalPrivateWireD1}=await modules();
  const filename=path.join(folder(t),'vault.sqlite'),wire=Buffer.from([0,255,128,10,13,0,42]);
  let binding=openLocalPrivateWireD1(filename);
  const first=await createLocalPrivateWire(binding,claim(wire),wire,()=>true);
  assert.equal(first.status,'LOCAL_CREATED');
  binding.close();
  binding=openLocalPrivateWireD1(filename);t.after(()=>binding.close());
  const read=await readLocalPrivateWire(binding,claim(wire),()=>true);
  assert.equal(read.status,'LOCAL_READBACK');
  assert.deepEqual(Buffer.from(read.wire),wire);
  assert.equal(read.independent_retention_proof,false);
  assert.equal(read.retention_status,'RETENTION_UNVERIFIED');
});

test('default, truthy, throwing and mutating gates make zero binding calls',async()=>{
  const {createLocalPrivateWire,readLocalPrivateWire}=await modules();
  let calls=0;const binding={prepare(){calls++;throw Error('private');},batch(){calls++;throw Error('private');}};
  const wire=Buffer.from('FICTIONAL_OPAQUE_WIRE'),c=claim(wire);
  for(const gate of [undefined,()=>false,()=>1,()=>{throw Error('FICTIONAL_SECRET');},copy=>{copy.owner_ref='changed';return true;}]){
    await assert.rejects(createLocalPrivateWire(binding,c,wire,gate),/LOCAL_PRIVATE_WIRE_REJECTED/);
    await assert.rejects(readLocalPrivateWire(binding,c,gate),/LOCAL_PRIVATE_WIRE_REJECTED/);
  }
  assert.equal(calls,0);
});

test('absent reads are unresolved and create no file or schema',async t=>{
  const m=await modules(),filename=path.join(folder(t),'absent.sqlite'),wire=Buffer.from('missing');
  const b=m.openLocalPrivateWireD1(filename);
  const result=await m.readLocalPrivateWire(b,claim(wire),()=>true);
  assert.equal(result.status,'UNRESOLVED');assert.equal(result.wire,null);
  assert.equal(existsSync(filename),false);assert.equal(b.stats.writeBatches,0);
});

test('binary boundaries retain every byte through four MiB and eight chunks',async t=>{
  const m=await modules(),filename=path.join(folder(t),'boundaries.sqlite'),b=m.openLocalPrivateWireD1(filename);
  for(const size of [1,CHUNK-1,CHUNK,CHUNK+1,4194303,4194304]){
    const wire=Uint8Array.from({length:size},(_,i)=>(i*17+255)%256),c=claim(wire);
    const result=await m.createLocalPrivateWire(b,c,wire,()=>true);
    assert.deepEqual(result.wire,wire);assert.equal(result.chunk_count,Math.ceil(size/CHUNK));
  }
  assert.equal(b.stats.maxBodyBytesMaterialized,CHUNK);
});

test('early strict types, oversized inputs and claim getters deny before hash or binding',async()=>{
  const m=await modules(),wire=Buffer.from('opaque'),c=claim(wire);
  let calls=0,hashes=0,accessors=0;
  const binding={prepare(){calls++;throw Error();},batch(){calls++;throw Error();}};
  const digest=crypto.subtle.digest.bind(crypto.subtle),original=crypto.subtle.digest;
  crypto.subtle.digest=(...args)=>{hashes++;return digest(...args);};
  try{
    const getter={...c};Object.defineProperty(getter,'owner_ref',{get(){accessors++;return 'bad';},enumerable:true});
    const symbolic={...c,[Symbol('x')]:true};
    for(const bad of [{...c,wire_bytes:true},{...c,owner_ref:'x'.repeat(8*1024*1024)},
      {...c,extra:'x'},getter,symbolic,{...c,model_source_sha40:'f'.repeat(64)},
      {...c,destination_ref:'local-private-vault:wrong'},Object.assign(Object.create({}),c)]){
      await assert.rejects(m.createLocalPrivateWire(binding,bad,wire,()=>true));
    }
    await assert.rejects(m.createLocalPrivateWire(binding,c,new Uint8Array(4194305),()=>true));
    assert.equal(calls,0);assert.equal(hashes,0);assert.equal(accessors,0);
  }finally{crypto.subtle.digest=original;}
});

test('UTC microseconds and original timestamp spellings are preserved',async t=>{
  const m=await modules(),filename=path.join(folder(t),'time.sqlite'),b=m.openLocalPrivateWireD1(filename),wire=Buffer.from('time');
  const good=claim(wire,{retain_until:'2030-01-15T00:16:00.123457+00:00'});
  const result=await m.createLocalPrivateWire(b,good,wire,()=>true);
  assert.equal(result.claim.retain_until,good.retain_until);
  for(const value of ['2030-01-15T00:16:00.123456+00:00','2030-01-15T00:16:00.123455Z','2030-02-30T01:00:00Z',
      '2030-01-15T01:00:00+01:00','2030-01-15T00:16:00.1234578Z','0000-01-01T00:00:00Z']){
    const n=b.stats.batch;await assert.rejects(m.createLocalPrivateWire(b,claim(wire,{retain_until:value}),wire,()=>true));assert.equal(b.stats.batch,n);
  }
});

test('caller closure mutations cannot rewrite a snapshotted claim or wire',async t=>{
  const m=await modules(),b=m.openLocalPrivateWireD1(path.join(folder(t),'owned.sqlite'));
  const wire=Buffer.from('original private binary'),before=Buffer.from(wire),c=claim(wire),owner=c.owner_ref;
  const result=await m.createLocalPrivateWire(b,c,wire,async()=>{wire.fill(0);c.owner_ref='mutated original';await delay(1);return true;});
  assert.deepEqual(Buffer.from(result.wire),before);assert.equal(result.claim.owner_ref,owner);
  result.wire.fill(0);
  assert.deepEqual(Buffer.from((await m.readLocalPrivateWire(b,claim(before),()=>true)).wire),before);
});

test('known equality is read only and complete scope prevents deduplication',async t=>{
  const m=await modules(),filename=path.join(folder(t),'scope.sqlite'),b=m.openLocalPrivateWireD1(filename),wire=Buffer.from('same body'),c=claim(wire);
  const first=await m.createLocalPrivateWire(b,c,wire,()=>true),before=readFileSync(filename),writes=b.stats.writeBatches;
  const again=await m.createLocalPrivateWire(b,c,wire,()=>true);
  assert.equal(again.status,'LOCAL_READBACK');assert.equal(again.locator,first.locator);assert.equal(b.stats.writeBatches,writes);assert.deepEqual(readFileSync(filename),before);
  for(const overrides of [{owner_ref:'another owner'},{destination_ref:'local-private-vault-other'},
      {retention_request_sha256:'1'.repeat(64)},{reservation_row_sha256:'2'.repeat(64)}]){
    const next=await m.createLocalPrivateWire(b,claim(wire,overrides),wire,()=>true);assert.notEqual(next.locator,first.locator);
  }
  const db=new DatabaseSync(filename,{readOnly:true});
  try{assert.equal(db.prepare('SELECT count(*) n FROM private_wire_chunks_v1').get().n,5);}finally{db.close();}
});

test('foreign schema and raced foreign schema never acquire vault tables',async t=>{
  const m=await modules(),dir=folder(t),wire=Buffer.from('foreign');
  for(const race of [false,true]){
    const filename=path.join(dir,String(race)+'.sqlite');
    const putForeign=()=>{const db=new DatabaseSync(filename);db.exec('CREATE TABLE foreign_data(value TEXT)');db.prepare('INSERT INTO foreign_data VALUES(?)').run('FICTIONAL_PRIVATE_FOREIGN');db.close();};
    if(!race)putForeign();
    const before=race?null:readFileSync(filename);
    let inserted=false;
    const b=m.openLocalPrivateWireD1(filename,{beforeBegin({writable}){if(race&&writable&&!inserted){inserted=true;putForeign();}}});
    await assert.rejects(m.createLocalPrivateWire(b,claim(wire),wire,()=>true));
    if(before)assert.deepEqual(readFileSync(filename),before);
    const db=new DatabaseSync(filename,{readOnly:true});
    try{assert.deepEqual(db.prepare("SELECT name FROM sqlite_schema WHERE type='table'").all().map(r=>r.name),['foreign_data']);}finally{db.close();}
  }
});

test('legal sqliteX names cannot hide foreign schema before or during initialization',async t=>{
  const m=await modules(),dir=folder(t),wire=Buffer.from('hidden foreign'),c=claim(wire);
  for(const race of [false,true]){
    const filename=path.join(dir,'hidden-'+race+'.sqlite');
    const foreign=()=>{const db=new DatabaseSync(filename);db.exec('CREATE TABLE sqliteXforeign(value TEXT)');db.prepare('INSERT INTO sqliteXforeign VALUES(?)').run('FICTIONAL_PRIVATE_FOREIGN');db.close();};
    if(!race)foreign();
    const before=race?null:readFileSync(filename);let inserted=false;
    const b=m.openLocalPrivateWireD1(filename,{beforeBegin({writable}){if(race&&writable&&!inserted){inserted=true;foreign();}}});
    await assert.rejects(m.createLocalPrivateWire(b,c,wire,()=>true));
    if(before)assert.deepEqual(readFileSync(filename),before);
    const db=new DatabaseSync(filename,{readOnly:true});
    try{assert.deepEqual(db.prepare("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name").all().map(row=>row.name),['sqliteXforeign']);}finally{db.close();}
  }
});

test('middle and final chunk failures rollback metadata, chunks and initialization',async t=>{
  const m=await modules(),wire=new Uint8Array(CHUNK*3+1),c=claim(wire),dir=folder(t);
  for(const index of [1,3]){
    const filename=path.join(dir,'fault'+index+'.sqlite');
    const b=m.openLocalPrivateWireD1(filename,{beforeStatement({sql,params}){if(sql.startsWith('INSERT INTO private_wire_chunks_v1'))params[index*4+3]=new Uint8Array();}});
    await assert.rejects(m.createLocalPrivateWire(b,c,wire,()=>true));
    const db=new DatabaseSync(filename,{readOnly:true});
    try{assert.equal(db.prepare("SELECT count(*) n FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'").get().n,0);assert.equal(db.prepare('PRAGMA application_id').get().application_id,0);}finally{db.close();}
  }
});

function alter(filename,table,sql,params=[]){
  const db=new DatabaseSync(filename);
  try{
    db.exec('PRAGMA ignore_check_constraints=ON');
    const trigger=db.prepare('SELECT sql FROM sqlite_schema WHERE name=?').get(table+'_no_update').sql;
    db.exec('DROP TRIGGER '+table+'_no_update');db.prepare(sql).run(...params);db.exec(trigger);
  }finally{db.close();}
}
test('oversized SQL bodies are excluded before JavaScript materialization',async t=>{
  const m=await modules(),filename=path.join(folder(t),'large.sqlite'),wire=Buffer.from('large'),c=claim(wire);
  await m.createLocalPrivateWire(m.openLocalPrivateWireD1(filename),c,wire,()=>true);
  alter(filename,'private_wire_chunks_v1','UPDATE private_wire_chunks_v1 SET body=zeroblob(16777216)');
  const b=m.openLocalPrivateWireD1(filename),before=readFileSync(filename);
  assert.equal((await m.readLocalPrivateWire(b,c,()=>true)).status,'UNRESOLVED');assert.equal(b.stats.bodyBytesMaterialized,0);
  await assert.rejects(m.createLocalPrivateWire(b,c,wire,()=>true));assert.equal(b.stats.writeBatches,0);assert.deepEqual(readFileSync(filename),before);
});

test('partial or corrupt existing objects are never repaired',async t=>{
  const m=await modules(),filename=path.join(folder(t),'partial.sqlite'),wire=new Uint8Array(CHUNK+3),c=claim(wire);
  await m.createLocalPrivateWire(m.openLocalPrivateWireD1(filename),c,wire,()=>true);
  const db=new DatabaseSync(filename),trigger=db.prepare("SELECT sql FROM sqlite_schema WHERE name='private_wire_chunks_v1_no_delete'").get().sql;
  db.exec('DROP TRIGGER private_wire_chunks_v1_no_delete');db.exec('DELETE FROM private_wire_chunks_v1 WHERE ordinal=1');db.exec(trigger);db.close();
  const b=m.openLocalPrivateWireD1(filename),before=readFileSync(filename);
  await assert.rejects(m.createLocalPrivateWire(b,c,wire,()=>true));assert.equal(b.stats.writeBatches,0);assert.deepEqual(readFileSync(filename),before);
  assert.equal((await m.readLocalPrivateWire(b,c,()=>true)).status,'UNRESOLVED');
});

test('whole-object scalar preflight rejects before fetching any valid-sized body',async t=>{
  const m=await modules(),dir=folder(t),wire=new Uint8Array(CHUNK+3),c=claim(wire);
  for(const [name,table,sql] of [
    ['metadata','private_wire_objects_v1',"UPDATE private_wire_objects_v1 SET claim_json='{}'"],
    ['ordinal','private_wire_chunks_v1','UPDATE private_wire_chunks_v1 SET ordinal=7 WHERE ordinal=1'],
    ['digest','private_wire_chunks_v1',"UPDATE private_wire_chunks_v1 SET chunk_sha256='"+'0'.repeat(64)+"' WHERE ordinal=1"]]){
    const filename=path.join(dir,name+'.sqlite');
    await m.createLocalPrivateWire(m.openLocalPrivateWireD1(filename),c,wire,()=>true);
    alter(filename,table,sql);
    const b=m.openLocalPrivateWireD1(filename);
    assert.equal((await m.readLocalPrivateWire(b,c,()=>true)).status,'UNRESOLVED');
    assert.equal(b.stats.bodyBytesMaterialized,0,name);
  }
});

test('SQL guards prevent mutation and late extra chunks',async t=>{
  const m=await modules(),filename=path.join(folder(t),'guards.sqlite'),wire=Buffer.from('guard');
  const result=await m.createLocalPrivateWire(m.openLocalPrivateWireD1(filename),claim(wire),wire,()=>true),db=new DatabaseSync(filename);
  try{
    for(const sql of ['DELETE FROM private_wire_objects_v1','UPDATE private_wire_objects_v1 SET wire_bytes=1','DELETE FROM private_wire_chunks_v1','UPDATE private_wire_chunks_v1 SET body=x\'00\''])assert.throws(()=>db.exec(sql));
    assert.throws(()=>db.prepare('INSERT INTO private_wire_chunks_v1 VALUES(?,?,?,?)').run(result.locator,1,'a'.repeat(64),new Uint8Array([0])));
  }finally{db.close();}
});

test('REPLACE cannot bypass create-only object and chunk protection',async t=>{
  const m=await modules(),filename=path.join(folder(t),'replace.sqlite'),wire=Buffer.from('replacement');
  await m.createLocalPrivateWire(m.openLocalPrivateWireD1(filename),claim(wire),wire,()=>true);
  const db=new DatabaseSync(filename);
  try{
    assert.throws(()=>db.exec('INSERT OR REPLACE INTO private_wire_objects_v1 SELECT locator,claim_json,wire_sha256,1,1 FROM private_wire_objects_v1'));
    assert.throws(()=>db.exec("INSERT OR REPLACE INTO private_wire_chunks_v1 SELECT locator,ordinal,chunk_sha256,zeroblob(length(body)) FROM private_wire_chunks_v1"));
  }finally{db.close();}
});

test('32 object and 16 MiB caps are atomic while equality at cap stays read only',async t=>{
  const m=await modules(),dir=folder(t),small=Buffer.from('x'),one=m.openLocalPrivateWireD1(path.join(dir,'count.sqlite'));
  for(let i=0;i<32;i++)await m.createLocalPrivateWire(one,claim(small,{owner_ref:'owner'+i}),small,()=>true);
  const before=one.stats.writeBatches;
  assert.equal((await m.createLocalPrivateWire(one,claim(small,{owner_ref:'owner0'}),small,()=>true)).status,'LOCAL_READBACK');assert.equal(one.stats.writeBatches,before);
  await assert.rejects(m.createLocalPrivateWire(one,claim(small,{owner_ref:'owner32'}),small,()=>true));
  const full=new Uint8Array(4194304),two=m.openLocalPrivateWireD1(path.join(dir,'bytes.sqlite'));
  for(let i=0;i<4;i++)await m.createLocalPrivateWire(two,claim(full,{owner_ref:'owner'+i}),full,()=>true);
  await assert.rejects(m.createLocalPrivateWire(two,claim(small),small,()=>true));
});

test('unknown write acknowledgment has no retry and exact read recovers without a write',async t=>{
  const m=await modules(),filename=path.join(folder(t),'unknown.sqlite'),wire=Buffer.from('unknown ack'),c=claim(wire);
  const b=m.openLocalPrivateWireD1(filename,{afterCommit({writable}){if(writable)throw Error('FICTIONAL_SECRET_PATH_TOKEN');}});
  await assert.rejects(m.createLocalPrivateWire(b,c,wire,()=>true),error=>error.message==='LOCAL_PRIVATE_WIRE_WRITE_UNCERTAIN_READ_ONLY'&&!String(error.stack).includes('FICTIONAL_SECRET_PATH_TOKEN'));
  assert.equal(b.stats.writeBatches,1);
  const r=m.openLocalPrivateWireD1(filename),result=await m.readLocalPrivateWire(r,c,()=>true);
  assert.deepEqual(Buffer.from(result.wire),wire);assert.equal(r.stats.writeBatches,0);
});

test('missing SQL guard acknowledgment is never accepted as a successful protocol',async t=>{
  const m=await modules(),filename=path.join(folder(t),'bad-ack.sqlite'),wire=Buffer.from('guard ack'),c=claim(wire);
  const underlying=m.openLocalPrivateWireD1(filename),binding={prepare:sql=>underlying.prepare(sql),
    async batch(statements){const r=await underlying.batch(statements);if(statements[0].sql.includes('AS admitted'))r[0].results=[];return r;}};
  await assert.rejects(m.createLocalPrivateWire(binding,c,wire,()=>true));
  assert.equal((await m.readLocalPrivateWire(binding,c,()=>true)).status,'UNRESOLVED');
  assert.equal((await m.readLocalPrivateWire(m.openLocalPrivateWireD1(filename),c,()=>true)).status,'LOCAL_READBACK');
});

test('test adapter refuses Git targets, hardlinked aliases and lexical remote paths',async t=>{
  const m=await modules(),dir=folder(t),wire=Buffer.from('path'),c=claim(wire);
  const repo=path.join(dir,'repo');mkdirSync(repo);writeFileSync(path.join(repo,'.git'),'gitdir: fictional');
  const hidden=path.join(repo,'vault.sqlite');
  await assert.rejects(m.createLocalPrivateWire(m.openLocalPrivateWireD1(hidden),c,wire,()=>true));assert.equal(existsSync(hidden),false);
  const original=path.join(repo,'original.sqlite'),alias=path.join(dir,'alias.sqlite');writeFileSync(original,'');linkSync(original,alias);
  await assert.rejects(m.createLocalPrivateWire(m.openLocalPrivateWireD1(alias),c,wire,()=>true));assert.equal(readFileSync(original).length,0);
  for(const file of ['\\\\fictional-do-not-connect.invalid\\share\\vault.sqlite','//fictional-do-not-connect.invalid/share/vault.sqlite']){
    const result=await m.readLocalPrivateWire(m.openLocalPrivateWireD1(file),c,()=>true);assert.equal(result.status,'UNRESOLVED');
  }
});

async function child(mode,dir,filename,wire){
  const config=path.join(dir,'config-'+mode+'.json'),raw=path.join(dir,'wire-'+mode+'.bin');
  writeFileSync(config,JSON.stringify(claim(wire)));writeFileSync(raw,wire);
  const p=spawn(process.execPath,[fileURLToPath(import.meta.url),'--vault-worker',mode,filename,config,raw,dir],{stdio:['ignore','pipe','pipe']});
  let stdout='',stderr='';p.stdout.on('data',b=>stdout+=b);p.stderr.on('data',b=>stderr+=b);
  const done=new Promise(resolve=>p.once('close',code=>resolve({code,stdout,stderr})));
  return {p,done};
}
async function until(filename){const end=Date.now()+15000;while(!existsSync(filename)&&Date.now()<end)await delay(10);assert.ok(existsSync(filename),'child synchronization missing');}
test('two real processes overlap under one transaction and return the same object',async t=>{
  const dir=folder(t),filename=path.join(dir,'concurrent.sqlite'),wire=new Uint8Array(CHUNK+1);
  const a=await child('hold',dir,filename,wire);t.after(()=>a.p.exitCode===null&&a.p.kill());
  await until(path.join(dir,'holding'));
  const b=await child('overlap',dir,filename,wire);t.after(()=>b.p.exitCode===null&&b.p.kill());
  await until(path.join(dir,'competing'));assert.equal(b.p.exitCode,null);writeFileSync(path.join(dir,'release'),'');
  const [ra,rb]=await Promise.all([a.done,b.done]);assert.equal(ra.code,0,ra.stderr);assert.equal(rb.code,0,rb.stderr);
  const ja=JSON.parse(ra.stdout),jb=JSON.parse(rb.stdout);assert.equal(ja.locator,jb.locator);assert.deepEqual([ja.status,jb.status],['LOCAL_CREATED','LOCAL_READBACK']);
});
test('real process death before or after commit stays read-only on recovery',async t=>{
  const m=await modules(),dir=folder(t),wire=Buffer.from('crash bytes'),c=claim(wire);
  for(const mode of ['before','after']){
    const filename=path.join(dir,mode+'.sqlite'),p=await child(mode,dir,filename,wire),result=await p.done;
    assert.equal(result.code,74,result.stderr);
    const b=m.openLocalPrivateWireD1(filename),read=await m.readLocalPrivateWire(b,c,()=>true);
    assert.equal(read.status,mode==='after'?'LOCAL_READBACK':'UNRESOLVED');assert.equal(b.stats.writeBatches,0);
  }
});
async function worker(mode,filename,config,raw,dir){
  const m=await modules(),c=JSON.parse(readFileSync(config,'utf8')),wire=readFileSync(raw),sleep=new Int32Array(new SharedArrayBuffer(4));
  const b=m.openLocalPrivateWireD1(filename,{
    beforeBegin({writable}){if(writable&&mode==='overlap')writeFileSync(path.join(dir,'competing'),'');},
    beforeCommit({writable}){if(!writable)return;if(mode==='before')process.exit(74);if(mode==='hold'){writeFileSync(path.join(dir,'holding'),'');const end=Date.now()+20000;while(!existsSync(path.join(dir,'release'))&&Date.now()<end)Atomics.wait(sleep,0,0,10);}},
    afterCommit({writable}){if(writable&&mode==='after')process.exit(74);}
  });
  const result=await m.createLocalPrivateWire(b,c,wire,()=>true);console.log(JSON.stringify({locator:result.locator,status:result.status}));
}
