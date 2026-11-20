'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {createHash}=require('node:crypto');
const modulePath='../web/keirin-note-model.js';
function source(value){const text=JSON.stringify(value);return {text,sha256:createHash('sha256').update(text).digest('hex'),bytes:Buffer.byteLength(text)};}
function packet(){return {schema:'RACE_AI_KEIRIN_NOTE_VIEW_V1',formal_model_admission:false,production_weight_switch:false,source_commit:'a'.repeat(40),imported_at:'2030-01-15T00:00:00Z',dates:['2030-01-15'],files:{
 'data/2030-01-15/races.json':source({races:[{race_id:'203001159801',venue:'架空場',race_no:1,deadline_time:'12:00',start_time:'12:05',riders:[1,2,3].map(number=>({number,name:'架空'+number,score:80})),lines:[[1,2],[3]],source_url:'https://keirin.kdreams.jp/test/racedetail/9820300115010001/'}]}),
 'data/2030-01-15/forecasts.json':source([{race_id:'203001159801',tickets:[{combo:'1-2-3',role:'本線'},{combo:'3-2-1',role:'波乱'}],scenarios:[],headline:'架空の分析'}]),
 'data/2030-01-15/flexible_forecasts.json':source({races:[{race_id:'203001159801',markets:{'3t':{tickets:[{combo:'2-1-3',role:'本線'}]},'2t':{tickets:[{combo:'2-1',role:'本線'}]}}}]}),
 'data/2030-01-15/reference_AB.json':source([{input:{race_id:'203001159801'},output:{race_id:'203001159801',A:{ranked_tickets:[[3,1,2]]},B:{ranked_tickets:[[2,3,1]]},C:{state:'HOLD_NO_INDEPENDENT_HISTORICAL_FOLLOW_LABELS'}}}])}};}
test('preserves original, flexible and reference tickets as separate views',async()=>{const M=require(modulePath),p=packet(),before=JSON.stringify(p);const data=await M.openPacket(p);const row=M.rows(data,'2030-01-15')[0];assert.equal(M.forecast(row,'3t','original').tickets[0].combo,'1-2-3');assert.equal(M.forecast(row,'3t','flexible').tickets[0].combo,'2-1-3');assert.equal(M.forecast(row,'2t','flexible').tickets[0].combo,'2-1');assert.equal(M.forecast(row,'3t','A').tickets[0].combo,'3-1-2');assert.equal(M.forecast(row,'3t','C').tickets.length,0);assert.equal(JSON.stringify(p),before);});
test('allocation excludes unchecked candidates without changing originals',async()=>{const M=require(modulePath),data=await M.openPacket(packet()),r=M.rows(data,'2030-01-15')[0];const out=M.allocate(M.forecast(r,'3t','original'),2500,new Set(['3-2-1']));assert.equal(out.total,2500);assert.deepEqual(out.amounts,[2500,0]);assert.equal(M.forecast(r,'3t','original').tickets.length,2);assert.equal(M.allocate(M.forecast(r,'3t','A'),2500,new Set()).available,false);});
test('rejects changed bytes and any claim of formal model admission',async()=>{const M=require(modulePath),p=packet();p.files['data/2030-01-15/races.json'].text+=' ';await assert.rejects(()=>M.openPacket(p));const q=packet();q.formal_model_admission=true;await assert.rejects(()=>M.openPacket(q));});
test('rejects duplicate starters and tickets with impossible cars',async()=>{const M=require(modulePath),p=packet();const name='data/2030-01-15/races.json',r=JSON.parse(p.files[name].text);r.races[0].riders.push(r.races[0].riders[0]);p.files[name]=source(r);await assert.rejects(()=>M.openPacket(p));const q=packet();q.files['data/2030-01-15/forecasts.json']=source([{race_id:'203001159801',tickets:[{combo:'1-2-9',role:'本線'}]}]);await assert.rejects(()=>M.openPacket(q));});
test('source links accept only attributed public providers',()=>{const M=require(modulePath);assert.equal(M.safeUrl('javascript:alert(1)'),null);assert.equal(M.safeUrl('https://user:pass@keirin.kdreams.jp/a'),null);assert.equal(M.safeUrl('https://evil.invalid/a'),null);assert.equal(M.safeUrl('https://keirin.netkeiba.com/race/entry/?race_id=203001159801'),'https://keirin.netkeiba.com/race/entry/?race_id=203001159801');});
test('two-car analysis keeps the original shared scenario roots',async()=>{const M=require(modulePath),p=packet(),name='data/2030-01-15/forecasts.json',original=JSON.parse(p.files[name].text);original[0].scenarios=[{label:'架空の先行展開',phases:[{description:'架空の隊列'}]}];p.files[name]=source(original);const d=await M.openPacket(p),r=M.rows(d,'2030-01-15')[0];assert.equal(M.forecast(r,'2t','original').scenarios[0]?.label,'架空の先行展開');});
test('keeps the attributed reference input alongside its unchanged research output',async()=>{const M=require(modulePath),p=packet(),name='data/2030-01-15/reference_AB.json',entries=JSON.parse(p.files[name].text);entries[0].input.source_pages=[{kind:'RACECARD',url:'https://keirin.netkeiba.com/race/entry/?race_id=203001159801'},{kind:'LINE',url:'https://keirin.kdreams.jp/test/racedetail/9820300115010001/'}];p.files[name]=source(entries);const d=await M.openPacket(p),r=M.rows(d,'2030-01-15')[0];assert.ok(r.referenceEnvelope?.input,'reference input provenance must remain accessible');assert.deepEqual(r.referenceEnvelope.input.source_pages,entries[0].input.source_pages);assert.deepEqual(r.reference,entries[0].output);assert.equal(M.forecast(r,'3t','B').tickets[0].combo,'2-3-1');});
module.exports={packet,source};

const RF=require('./keirin_note_result_fixtures.cjs');
test('opens a source-bound result-only packet without inventing a roster or forecast coverage',async()=>{
 const M=require(modulePath),obs=RF.observation(),p=RF.resultsPacket([obs]);
 const data=await M.openPacket(p);
 assert.equal(M.rows(data,RF.DAY).length,0);
 assert.equal(data.cipherSha,null);
 assert.equal(data.results.get(RF.RACE)[0].observation.observation_sha256,obs.observation_sha256);
 assert.equal(data.results.get(RF.RACE)[0].binding.fileSha256,p.files['data/'+RF.DAY+'/research_results.json'].sha256);
});
test('rejects result fact tampering and incorrect date, identity, receipts or formal flags',async()=>{
 const M=require(modulePath);
 const variants=[o=>o.winning_triple=[1,2,3],o=>o.race_id='203001169801',o=>o.provider_receipts[1].source_url='https://keirin.netkeiba.com/race/result/?race_id=203001159802',o=>o.qualifies_for_formal_settlement=true,o=>o.extra='unreviewed',o=>o.previous_observation_sha256=o.observation_sha256];
 for(const alter of variants){const o=RF.observation();alter(o);await assert.rejects(()=>M.openPacket(RF.resultsPacket([o])));}
 const p=packet();p.files['data/'+RF.DAY+'/reference_AB.json']=source([{input:{race_id:RF.RACE},output:{race_id:'203001159802',A:{ranked_tickets:[[1,2,3]]}}}]);
 await assert.rejects(()=>M.openPacket(p));
});
test('scores exact saved ticket counts with 100-yen arithmetic and a separate unknown two-car payout',async()=>{
 const M=require(modulePath),F=require('../web/keirin-note-feed.js');
 const data=F.merge([await M.openPacket(packet()),await M.openPacket(RF.resultsPacket([RF.observation()]))]),row=M.rows(data,RF.DAY)[0];
 const before=JSON.stringify(row.original),a=M.compare(row,'3t','A'),b=M.compare(row,'3t','B');
 assert.equal(a.status,'RESEARCH_HIT');assert.equal(a.ticketCount,1);assert.equal(a.hitAt1,true);assert.equal(a.stakeYen,100);assert.equal(a.payoutYen,5300);assert.equal(a.netYen,5200);
 assert.equal(a.formal,false);assert.equal(a.timingStatus,'GENERATED_AT_MISSING');assert.equal(a.predictionBinding.fileSha256,packet().files['data/'+RF.DAY+'/reference_AB.json'].sha256);
 assert.equal(b.status,'RESEARCH_MISS');assert.equal(b.payoutYen,0);assert.equal(b.netYen,-100);
 const two={...row,two:{race_id:RF.RACE,tickets:[{combo:'3-1',role:'本線'}]},bindings:{...row.bindings,two:row.bindings.original}};
 const score=M.compare(two,'2t','original');assert.equal(score.status,'RESEARCH_HIT');assert.equal(score.payoutYen,null);assert.equal(score.netYen,null);
 assert.equal(JSON.stringify(row.original),before);
});
test('keeps a twelve-point research hit distinct from Hit@8 and marks late generation nonformal',async()=>{
 const M=require(modulePath),F=require('../web/keirin-note-feed.js'),p=packet();
 const roster=JSON.parse(p.files['data/'+RF.DAY+'/races.json'].text);roster.races[0].riders.push({number:4,name:'架空4'});p.files['data/'+RF.DAY+'/races.json']=source(roster);
 const ranked=[[1,2,3],[1,2,4],[1,3,2],[1,3,4],[1,4,2],[1,4,3],[2,1,3],[2,1,4],[2,3,1],[2,3,4],[2,4,1],[3,1,2]];
 p.files['data/'+RF.DAY+'/reference_AB.json']=source([{input:{race_id:RF.RACE},output:{race_id:RF.RACE,generated_at:'2030-01-15T03:01:00Z',A:{ranked_tickets:ranked}}}]);
 const row=M.rows(F.merge([await M.openPacket(p),await M.openPacket(RF.resultsPacket([RF.observation()]))]),RF.DAY)[0],score=M.compare(row,'3t','A');
 assert.equal(score.ticketCount,12);assert.equal(score.stakeYen,1200);assert.equal(score.payoutYen,5300);assert.equal(score.netYen,4100);assert.equal(score.hitAt1,false);
 assert.equal(score.timingStatus,'GENERATED_AFTER_OR_AT_CUTOFF');assert.equal(score.formal,false);assert.equal(Object.hasOwn(score,'hitAt8'),false);
});
test('cipher identity comes only from verified encrypted bytes and remains bound to every forecast version',async()=>{
 const {createCipheriv,randomBytes}=require('node:crypto'),M=require(modulePath),F=require('../web/keirin-note-feed.js');
 async function sealed(p){const plain=Buffer.from(JSON.stringify(p)),header={schema:'RACE_AI_SAVED_WEB_VIEW_V1',source_content_sha256:RF.sha(plain.toString())},key=randomBytes(32),nonce=randomBytes(12),cipher=createCipheriv('aes-256-gcm',key,nonce);cipher.setAAD(Buffer.from(JSON.stringify(header)));const ciphertext=Buffer.concat([cipher.update(plain),cipher.final(),cipher.getAuthTag()]);const wire=Buffer.from(JSON.stringify({header,nonce:nonce.toString('base64'),ciphertext:ciphertext.toString('base64')})),cipherSha=RF.sha(wire.toString());return {data:await M.openCipher(new Uint8Array(wire),{cipherSha,key:key.toString('base64url')}),cipherSha};}
 const p=packet();p.cipherSha='f'.repeat(64);assert.equal((await M.openPacket(p)).cipherSha,null);
 const one=await sealed(p),two=await sealed(p);assert.equal(one.data.cipherSha,one.cipherSha);
 const merged=F.merge([one.data,two.data]),row=M.rows(merged,RF.DAY)[0];assert.equal(row.bindings.original.cipherSha,one.cipherSha);assert.equal(row.bindings.reference.cipherSha,two.cipherSha);assert.equal(row.referenceHistory[0].binding.cipherSha,one.cipherSha);
 assert.equal(row.referenceHistory[0].binding.fileSha256,p.files['data/'+RF.DAY+'/reference_AB.json'].sha256);
});
test('invalid UTC calendar dates and out-of-day packet rows are rejected before comparison',async()=>{
 const M=require(modulePath),o=RF.observation();o.captured_at='2030-02-30T03:10:00Z';await assert.rejects(()=>M.openPacket(RF.resultsPacket([o])));
 const q=packet(),name='data/'+RF.DAY+'/races.json',value=JSON.parse(q.files[name].text);value.races[0].race_id='203001169801';q.files[name]=source(value);await assert.rejects(()=>M.openPacket(q));
});
test('partial result deltas cannot score without the preceding history and HOLD accepts bounded receipt counts',async()=>{
 const M=require(modulePath),first=RF.observation({previous:'f'.repeat(64)}),p=packet();Object.assign(p.files,RF.resultsPacket([first]).files);
 const row=M.rows(await M.openPacket(p),RF.DAY)[0];assert.equal(M.compare(row).status,'RESEARCH_UNKNOWN');assert.equal(M.compare(row).reason,'RESULT_HISTORY_INCOMPLETE');
 for(const providers of [[],['Kdreams'],['Kdreams','netkeirin']]){const o=RF.observation({state:'HOLD_SECONDARY_RESULT_DISAGREEMENT',providers});assert.equal((await M.openPacket(RF.resultsPacket([o]))).results.get(RF.RACE).length,1);}
});
