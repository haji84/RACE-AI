// TEST ONLY, fixed pinned modules and one native SQLite path. No service/receipt.
import {readSync,openSync,closeSync,fstatSync,lstatSync,existsSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';

const ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const MAX=4194304,META=65536;
const FILES={
  'workers/private_wire_vault.mjs':'383264d3a676e04fc91a6c4956ef79d5bda709a09f6ad5b03e0d6062b6891024',
  'workers/private_wire_vault_schema.mjs':'950646a723ba6b6fed4446084a9f1510fb18b1540dcc0c5c5ff1cba0eae41b0c',
  'tests/support/local_private_wire_d1.mjs':'04c26b80e27110b891e297a0d615cf99e9db84446f4d1ee978274f64f88db215'
};
const fail=()=>{throw Error('LOCAL_VAULT_TEST_CHILD_REJECTED');};
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
function canonical(value){
  if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
  if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
  return JSON.stringify(value);
}
function outsideGit(file,directory=false){
  if(typeof file!=='string'||!path.isAbsolute(file)||/^(?:\\\\|\/\/)/.test(file))fail();
  let here=path.resolve(file);
  for(let leaf=true;;leaf=false){
    const stat=lstatSync(here,{throwIfNoEntry:false});
    if(!stat||stat.isSymbolicLink())fail();
    if(!leaf||directory){if(!stat.isDirectory()||existsSync(path.join(here,'.git')))fail();}
    else if(!stat.isFile()||stat.nlink!==1)fail();
    const parent=path.dirname(here);if(parent===here)break;here=parent;
  }
  return file;
}
function bounded(file,limit){
  const before=lstatSync(file);
  if(!before.isFile()||before.isSymbolicLink()||before.nlink!==1||before.size>limit)fail();
  const fd=openSync(file,'r');
  try{
    const info=fstatSync(fd);
    if(info.dev!==before.dev||info.ino!==before.ino||info.size>limit)fail();
    const bytes=Buffer.alloc(limit+1);
    let used=0;
    while(used<bytes.length){
      const count=readSync(fd,bytes,used,bytes.length-used,null);
      if(count===0)break;
      used+=count;
    }
    if(used!==info.size||used>limit||fstatSync(fd).size!==info.size)fail();
    return bytes.subarray(0,used);
  }finally{closeSync(fd);}
}
function exclusive(file,data,limit){
  if(data.byteLength>limit||existsSync(file))fail();
  writeFileSync(file,data,{flag:'wx',mode:0o600});
}
let binding;
try{
  if(process.version!=='v24.19.0'||process.argv.length!==3)fail();
  globalThis.fetch=()=>fail();
  const ipc=outsideGit(process.argv[2],true);
  const raw=bounded(path.join(ipc,'control.json'),META);
  const control=JSON.parse(raw.toString('utf8'));
  if(canonical(control)!==raw.toString('utf8')||Object.keys(control).sort().join(',')!=='claim,database_path,locator,operation,schema'
    ||control.schema!=='RACE_AI_LOCAL_VAULT_TEST_IPC_V1'||!['create','read'].includes(control.operation)
    ||typeof control.database_path!=='string'||!path.isAbsolute(control.database_path)
    ||typeof control.locator!=='string'||!(/^[a-f0-9]{64}$/).test(control.locator)
    ||Buffer.byteLength(canonical(control.claim))>8192
    ||sha(Buffer.from('RACE_AI_LOCAL_PRIVATE_WIRE_LOCATOR_V1\0'+canonical(control.claim)))!==control.locator)fail();
  outsideGit(path.dirname(control.database_path),true);
  if(existsSync(control.database_path))outsideGit(control.database_path);
  if(existsSync(path.join(ipc,'result.json'))||existsSync(path.join(ipc,'readback.bin')))fail();
  for(const [file,digest] of Object.entries(FILES)){
    if(sha(bounded(path.join(ROOT,'pr71-private-vault-reference',file),65536))!==digest)fail();
  }
  const load=file=>import(pathToFileURL(path.join(ROOT,'pr71-private-vault-reference',file)).href);
  const {createLocalPrivateWire,readLocalPrivateWire}=await load('workers/private_wire_vault.mjs');
  const {openLocalPrivateWireD1}=await load('tests/support/local_private_wire_d1.mjs');
  let wire=null;
  if(control.operation==='create')wire=new Uint8Array(bounded(path.join(ipc,'wire.bin'),MAX));
  else if(existsSync(path.join(ipc,'wire.bin')))fail();
  binding=openLocalPrivateWireD1(control.database_path);
  const admitted=async owned=>{if(canonical(owned)!==canonical(control.claim))fail();return true;}; // Authored local test only.
  const result=control.operation==='create'
    ?await createLocalPrivateWire(binding,control.claim,wire,admitted)
    :await readLocalPrivateWire(binding,control.claim,admitted);
  const present=result.wire!==null;
  if(present)exclusive(path.join(ipc,'readback.bin'),result.wire,MAX);
  const metadata={schema:'RACE_AI_LOCAL_VAULT_TEST_IPC_RESULT_V1',result:{...result,wire:null},wire_present:present};
  exclusive(path.join(ipc,'result.json'),Buffer.from(canonical(metadata)),META);
  binding.close();binding=null;
  process.stdout.write('{"schema":"RACE_AI_LOCAL_VAULT_TEST_CHILD_V1","status":"OK"}');
}catch{
  process.exitCode=1;
  process.stdout.write('{"schema":"RACE_AI_LOCAL_VAULT_TEST_CHILD_V1","status":"REJECTED"}');
}finally{
  if(binding)binding.close();
}
