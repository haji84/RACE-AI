// GitHub-only encrypted SQLite checkpoint. No provider calls or plaintext uploads.
import {createCipheriv,createDecipheriv,createHash,randomBytes,timingSafeEqual} from 'node:crypto';
import {openSync,closeSync,readFileSync,writeFileSync,fsyncSync,fstatSync,constants} from 'node:fs';
import {pathToFileURL} from 'node:url';

const MAX_DB=8*1024*1024, MAX_ENVELOPE=12*1024*1024;
const PREFIX=Buffer.from('SQLite format 3\0');
const SCOPE_KEYS=['generation','mode','previous_cipher_sha256','repository_id','schema'];
export class CheckpointError extends Error { constructor(code){super(code);this.name='CheckpointError';} }
function need(ok,code){if(!ok)throw new CheckpointError(code);}
export function syntheticKey(){return createHash('sha256').update('RACE_AI_PUBLIC_SYNTHETIC_FIXTURE_KEY_V1_NOT_FOR_REAL_DATA').digest();}
function scopeOf(value){
 need(value && typeof value==='object' && !Array.isArray(value),'SCOPE_REQUIRED');
 need(Object.keys(value).sort().join(',')===SCOPE_KEYS.join(','),'SCOPE_FIELDS_INVALID');
 need(value.schema==='RACE_AI_GITHUB_SQLITE_V1' && value.repository_id==='1416489937','REPOSITORY_SCOPE_INVALID');
 need(['synthetic','production'].includes(value.mode),'MODE_INVALID');
 need(Number.isSafeInteger(value.generation)&&value.generation>=1,'GENERATION_INVALID');
 need(value.generation===1 ? value.previous_cipher_sha256===null :
  typeof value.previous_cipher_sha256==='string'&&/^[0-9a-f]{64}$/.test(value.previous_cipher_sha256),'HISTORY_BINDING_INVALID');
 return {schema:value.schema,repository_id:value.repository_id,mode:value.mode,
         generation:value.generation,previous_cipher_sha256:value.previous_cipher_sha256};
}
function validKey(key,mode){
 need(Buffer.isBuffer(key)&&key.length===32,'KEY_MUST_BE_32_RANDOM_BYTES');
 if(mode==='production'){
  need(new Set(key).size>=8 && !timingSafeEqual(key,syntheticKey()),'PRODUCTION_KEY_IS_NOT_PRIVATE');
 }
 return key;
}
function decode64(value,max){
 need(typeof value==='string'&&value.length<=4*Math.ceil(max/3),'INVALID_BASE64');
 const out=Buffer.from(value,'base64');
 // Exact re-encoding rejects noncanonical input without a size-dependent regex stack.
 need(out.length<=max&&out.toString('base64')===value,'INVALID_BASE64');
 return out;
}
export function readKey(value,mode){
 need(typeof value==='string'&&value.length===44,'STATE_KEY_MISSING_OR_INVALID');
 return validKey(decode64(value,32),mode);
}
function sqliteBytes(data){
 need(Buffer.isBuffer(data)&&data.length>=PREFIX.length&&data.length<=MAX_DB,'SQLITE_SNAPSHOT_SIZE_INVALID');
 need(data.subarray(0,PREFIX.length).equals(PREFIX),'SQLITE_HEADER_INVALID');
}
export function seal(snapshot,key,scope){
 const header=scopeOf(scope);validKey(key,header.mode);sqliteBytes(snapshot);
 const iv=randomBytes(12), cipher=createCipheriv('aes-256-gcm',key,iv,{authTagLength:16});
 cipher.setAAD(Buffer.from(JSON.stringify(header)));
 const ciphertext=Buffer.concat([cipher.update(snapshot),cipher.final()]);
 return Buffer.from(JSON.stringify({header,nonce:iv.toString('base64'),
  ciphertext:ciphertext.toString('base64'),tag:cipher.getAuthTag().toString('base64')})+'\n');
}
export function unseal(envelope,key,expectedScope){
 const expected=scopeOf(expectedScope);validKey(key,expected.mode);
 need(Buffer.isBuffer(envelope)&&envelope.length>0&&envelope.length<=MAX_ENVELOPE,'ENVELOPE_SIZE_INVALID');
 let data;try{data=JSON.parse(envelope.toString('utf8'));}catch{throw new CheckpointError('ENVELOPE_JSON_INVALID');}
 need(data&&typeof data==='object'&&Object.keys(data).sort().join(',')==='ciphertext,header,nonce,tag','ENVELOPE_FIELDS_INVALID');
 const header=scopeOf(data.header);
 need(JSON.stringify(header)===JSON.stringify(expected),'UNEXPECTED_CHECKPOINT_SCOPE');
 const iv=decode64(data.nonce,12), tag=decode64(data.tag,16), ciphertext=decode64(data.ciphertext,MAX_DB);
 need(iv.length===12&&tag.length===16,'AEAD_PARAMETERS_INVALID');
 let plain;try{
  const decipher=createDecipheriv('aes-256-gcm',key,iv,{authTagLength:16});
  decipher.setAAD(Buffer.from(JSON.stringify(header)));decipher.setAuthTag(tag);
  plain=Buffer.concat([decipher.update(ciphertext),decipher.final()]);
 }catch{throw new CheckpointError('CHECKPOINT_AUTHENTICATION_FAILED');}
 sqliteBytes(plain);return plain;
}
export function writeOnce(path,bytes){
 let fd;try{
  fd=openSync(path,constants.O_WRONLY|constants.O_CREAT|constants.O_EXCL|(constants.O_NOFOLLOW||0),0o600);
  writeFileSync(fd,bytes);fsyncSync(fd);
 }catch{throw new CheckpointError('CREATE_ONLY_WRITE_FAILED');}
 finally{if(fd!==undefined)closeSync(fd);}
}
function readBounded(path,max){
 let fd;try{
  fd=openSync(path,constants.O_RDONLY|(constants.O_NOFOLLOW||0));
  const s=fstatSync(fd);need(s.isFile()&&s.size>0&&s.size<=max,'INPUT_SIZE_INVALID');
  const data=readFileSync(fd);need(data.length<=max,'INPUT_SIZE_INVALID');return data;
 }catch(e){if(e instanceof CheckpointError)throw e;throw new CheckpointError('REGULAR_INPUT_REQUIRED');}
 finally{if(fd!==undefined)closeSync(fd);}
}
export function main(argv=process.argv.slice(2)){
 try{
  need(argv.length===4&&['seal','unseal'].includes(argv[0]),'USAGE_ACTION_INPUT_OUTPUT_SCOPE_REQUIRED');
  const [action,input,output,scopeFile]=argv;
  let scope;try{scope=scopeOf(JSON.parse(readBounded(scopeFile,1024)));}catch{throw new CheckpointError('SCOPE_FILE_INVALID');}
  const key=scope.mode==='synthetic'?syntheticKey():readKey(process.env.RACE_AI_STATE_KEY,scope.mode);
  const raw=readBounded(input,action==='seal'?MAX_DB:MAX_ENVELOPE);
  if(action==='unseal'){
   need(/^[0-9a-f]{64}$/.test(process.env.RACE_AI_EXPECTED_CIPHER_SHA256||''),'PINNED_CIPHERTEXT_SHA_REQUIRED');
   need(createHash('sha256').update(raw).digest('hex')===process.env.RACE_AI_EXPECTED_CIPHER_SHA256,'CIPHERTEXT_SHA_MISMATCH');
  }
  const result=action==='seal'?seal(raw,key,scope):unseal(raw,key,scope);
  writeOnce(output,result);
  console.log(JSON.stringify({status:action==='seal'?'ENCRYPTED_SNAPSHOT_CREATED':'SNAPSHOT_DECRYPTED_CHECK_INTEGRITY',
   mode:scope.mode,generation:scope.generation,bytes:result.length,
   ciphertext_sha256:createHash('sha256').update(action==='seal'?result:raw).digest('hex'),
   plaintext_published:false}));
  return 0;
 }catch(e){console.log(JSON.stringify({status:'CHECKPOINT_FAILED_CLOSED',reason:e instanceof CheckpointError?e.message:'UNEXPECTED_FAILURE'}));return 2;}
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href)process.exitCode=main();
