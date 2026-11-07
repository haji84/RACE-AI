'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const M=require('../web/product-data.js'),P=require('../web/saved-performance.js');
const six=[[1,3,6],[1,6,3],[3,1,6],[3,6,1],[6,1,3],[6,3,1]];
const group={scope:'synthetic',sport:'boat',model_id:'fictional-model',model_version:'v1',stage:'P1',variant:'NATIVE'};
function fixture(){
 const p={model_id:'fictional-model',model_version:'v1',stage:'P1',variant:'NATIVE',ordered_top8:structuredClone(six),ordered_candidates:structuredClone(six),
  prediction_sha256:'a'.repeat(64),input_sha256:'b'.repeat(64),source_sha256:'c'.repeat(64),
  as_of:'2030-04-01T09:00:00+09:00',generated_at:'2030-04-01T09:00:01+09:00',persisted_at:'2030-04-01T09:01:00+09:00',
  cutoff_at:'2030-04-01T10:00:00+09:00',odds_independent:true,external_receipt_verified:false};
 return {schema:'RACE_AI_PRIVATE_CYCLE_VIEW_V1',dataset_status:'SYNTHETIC_ONLY',event_date_jst:'2030-04-01',records:[{
  race_id:'20300401-01-01',sport:'boat',venue:'合成場',race_no:1,event_date_jst:'2030-04-01',scope:'synthetic',
  offering_status:'UNKNOWN',cutoff_at:p.cutoff_at,saved_cutoff_variants:[p.cutoff_at],
  participants:[1,3,6].map(number=>({number,registration_no:String(4200+number),name:null})),
  prediction:p,comparison_predictions:[],result:null,result_observations:[],result_observation_rejections:[],result_revisions:[]}]};
}

test('same output at distinct saved as-ofs remains explicitly selectable',()=>{
 const raw=fixture(),row=raw.records[0],second=structuredClone(row.prediction);
 second.as_of='2030-04-01T09:00:01+09:00';row.comparison_predictions=[second];
 const before=JSON.stringify(raw),r=M.parse(raw).records[0];
 assert.equal(M.candidates(r).length,2);
 assert.equal(M.selectPrediction(r,{stage:'P1',modelId:'fictional-model',version:'v1',variant:'NATIVE'}),null,'an ambiguous original is not chosen silently');
 assert.equal(M.selectPrediction(r,{asOf:second.as_of}).as_of,second.as_of);
 assert.equal(M.selectPrediction(r,{saveIdentity:M.savedPredictionIdentity(r.comparison_predictions[0])}),r.comparison_predictions[0]);
 assert.equal(JSON.stringify(raw),before);
});

test('altered original under the same source clock and receipt binding is rejected',()=>{
 const raw=fixture(),row=raw.records[0];row.comparison_predictions=[{...structuredClone(row.prediction),prediction_sha256:'d'.repeat(64)}];
 assert.throws(()=>M.parse(raw));
});

test('display-name provenance cannot bind a different registration or race',()=>{
 for(const source of [{kind:'SAME_RACE_PROGRAM',registration_no:'4203',race_id:'20300401-01-01'},
  {kind:'SAME_RACE_PROGRAM',registration_no:'4201',race_id:'20300401-01-02'},
  {kind:'VERIFIED_RACER_REGISTRY',registration_no:'4201',verified:false,source_sha256:'a'.repeat(64)}]){
  const raw=fixture();Object.assign(raw.records[0].participants[0],{name:'合成選手',name_source:source});
  assert.throws(()=>M.parse(raw));
 }
});

test('same-model stage and version preserves every variant group and reports ambiguous saves',()=>{
 const raw=fixture(),row=raw.records[0];
 for(const stage of ['P0','P1'])for(const variant of ['HISTORY_BASELINE','HISTORY_ADDED'])row.comparison_predictions.push({...structuredClone(row.prediction),stage,variant});
 row.comparison_predictions.push({...structuredClone(row.prediction),as_of:'2030-04-01T09:00:01+09:00'});
 const groups=M.modelGroups(M.parse(raw).records);
 assert.equal(groups.length,5);
 const g=groups.find(g=>g.stage==='P1'&&g.variant==='NATIVE');
 assert.equal(g.ambiguous_originals,1);
 assert.equal(P.pick(M.parse(raw).records[0],g),null);
});

test('complete three-entrant six-ticket forecast compares and costs600yen',()=>{
 const r=fixture().records[0];r.result={status:'final',winning_combinations:[[1,3,6]],payout_yen_per_100:1200};
 assert.equal(P.compare(r,r.prediction).status,'HIT');
 const a=P.allocate(r,r.prediction,800);
 assert.equal(a.stake,600);assert.equal(a.held,200);
 assert.deepEqual(a.tickets.map(t=>t.amount),[100,100,100,100,100,100]);
 const s=P.simulate([r],group,800);
 assert.equal(s.spent,600);assert.equal(s.reserved,800);assert.equal(s.held,200);assert.equal(s.payout,1200);assert.equal(s.net,600);
});

test('partial six-of120 ticket list does not become a complete three-entrant forecast',()=>{
 const r=fixture().records[0];
 r.prediction.ordered_candidates=[...structuredClone(six),[1,2,3]];
 assert.equal(P.compare(r,r.prediction).status,'REVIEW');
 assert.equal(P.simulate([r],group,800).spent,0);
 delete r.prediction.ordered_candidates;
 assert.equal(P.compare(r,r.prediction).status,'REVIEW','a short roster alone is not proof of active status');
 r.roster_status='OFFICIAL_ACTIVE';
 assert.equal(P.compare(r,r.prediction).status,'PENDING');
 r.prediction.native_top8_available=false;
 assert.equal(P.compare(r,r.prediction).status,'REVIEW','partial seller plans remain excluded');
});

test('held short-plan budget is not reused to buy more races or topped up by rank',()=>{
 const r=fixture().records[0],rows=[1,2,3].map(n=>({...structuredClone(r),race_id:`20300401-01-0${n}`}));
 const s=P.simulate(rows,group,1600);
 assert.equal(s.bought,2);assert.equal(s.spent,1200);assert.equal(s.reserved,1600);assert.equal(s.held,400);
 assert.equal(s.rows[2].reason,'DAILY_BUDGET_LIMIT');
 const a=P.allocate(r,r.prediction,1000);
 assert.equal(a.stake,600);assert.equal(a.held,400);assert.ok(a.tickets.every(t=>t.amount===100));
});

test('three-entrant1000yen cap distributes400 only with distinct model support',()=>{
 const r=fixture().records[0],peer=structuredClone(r.prediction);peer.model_id='fictional-peer';
 r.comparison_predictions=[peer,{...structuredClone(peer),variant:'HISTORY_ADDED'}];
 const a=P.allocate(r,r.prediction,1000);
 assert.equal(a.stake,1000);assert.equal(a.held,0);
 assert.deepEqual(a.tickets.map(t=>t.amount),[200,200,200,200,100,100]);
 r.comparison_predictions.forEach(p=>p.model_id=r.prediction.model_id);
 assert.equal(P.allocate(r,r.prediction,1000).held,400,'same model variants are one family');
});

module.exports={fixture,six};

function reconciled(){
 const raw=fixture(),row=raw.records[0],first=row.cutoff_at,second='2030-04-01T10:01:00+09:00';
 row.cutoff_at=null;row.saved_cutoff_variants=[first,second];row.comparison_predictions=[{...structuredClone(row.prediction),stage:'P0',cutoff_at:second}];
 row.result_observations=[{race_id:row.race_id,captured_at:'2030-04-01T11:00:00+09:00',closed_at:second,source_sha256:'f'.repeat(64),status:'AVAILABLE',body_identity_verified:true,
  data:{status:'settled',confirmed:true,finish_confirmed:true,top3:[1,3,6],payouts:[{bet_type:'trifecta',combination:[1,3,6],payout_per_100_yen:1200}],results:row.participants.map((p,i)=>({lane:p.number,racer_registration_id:p.registration_no,finish:i+1,finish_status:'FINISHED'}))}}];
 row.result={status:'final',winning_combinations:[[1,3,6]],payout_yen_per_100:1200,observed_at:'2030-04-01T11:00:00+09:00',source_sha256:'f'.repeat(64),official:false,
  cutoff_reconciliation:{basis:'RAW_OFFICIAL_RESULT_PER_ORIGINAL_CUTOFF',formal_eligible:false,original_cutoffs:[first,second],source_sha256:'f'.repeat(64),maximum_offset_seconds:60,roster_identity_verified:true,all_originals_saved_before_both:true}};
 row.result_observation_rejections=[{captured_at:row.result.observed_at,source_sha256:'f'.repeat(64),reason:'RESULT_AMBIGUOUS_FORECAST_CUTOFF'}];
 return raw;
}
test('private one-minute result reconciliation preserves both original cutoffs and never becomes formal',()=>{
 const raw=reconciled(),parsed=M.parse(raw),row=parsed.records[0];
 assert.equal(row.result.status,'final');assert.equal(row.cutoff_at,null);
 assert.equal(row.result.cutoff_reconciliation.formal_eligible,false);assert.equal(M.eligibleResult(row),false);
 assert.equal(row.prediction.cutoff_at,'2030-04-01T10:00:00+09:00');
 assert.equal(row.comparison_predictions[0].cutoff_at,'2030-04-01T10:01:00+09:00');
});
test('one-minute reference result allows a known absent sixth entrant beside five active entrants',()=>{
 function withdrawn(){const raw=reconciled(),r=raw.records[0];r.participants.push(...[2,4].map(number=>({number,registration_no:String(4200+number)})));
  r.result_observations[0].data.results=r.participants.map((p,i)=>({lane:p.number,racer_registration_id:p.registration_no,finish:i+1,finish_status:'FINISHED'}));
  r.result_observations[0].data.results.push({lane:5,racer_registration_id:'4205',finish:null,finish_status:'ABSENT'});
  r.withdrawn_participants=[{number:5,registration_no:'4205'}];return raw;}
 for(const disposition of ['ABSENT','WITHDRAWN','RETURNED','欠']){const raw=withdrawn();raw.records[0].result_observations[0].data.results.at(-1).finish_status=disposition;
  const before=JSON.stringify(raw),r=M.parse(raw).records[0];assert.equal(r.result.status,'final');assert.equal(r.participants.length,5);assert.equal(M.eligibleResult(r),false);assert.equal(JSON.stringify(raw),before);}
 const fromSnapshot=withdrawn(),r=fromSnapshot.records[0];delete r.withdrawn_participants;r.saved_participant_rosters=[{race_id:r.race_id,participants:[...structuredClone(r.participants),{number:5,registration_no:'4205',active:false}]}];assert.equal(M.parse(fromSnapshot).records[0].result.status,'final');
 const mutations=[r=>delete r.withdrawn_participants,r=>r.withdrawn_participants[0].registration_no='4999',r=>r.result_observations[0].data.results.at(-1).finish=1,
  r=>r.result_observations[0].data.results.at(-1).finish_status='F',r=>r.result_observations[0].data.results.at(-1).finish_status='L',
  r=>r.result_observations[0].data.results.at(-1).verified_official=false,r=>r.withdrawn_participants[0].race_id='20300401-01-02'];
 for(const mutate of mutations){const raw=withdrawn();mutate(raw.records[0]);assert.throws(()=>M.parse(raw));}
});
test('result reconciliation rejects source roster schedule chronology and formal promotions',()=>{
 const mutations=[
  r=>r.result.cutoff_reconciliation.formal_eligible=true,
  r=>r.result.cutoff_reconciliation.original_cutoffs.pop(),
  r=>r.result.cutoff_reconciliation.maximum_offset_seconds=61,
  r=>r.result.cutoff_reconciliation.source_sha256='a'.repeat(64),
  r=>r.result.cutoff_reconciliation.roster_identity_verified=false,
  r=>r.result.cutoff_reconciliation.all_originals_saved_before_both=false,
  r=>r.result_observations[0].body_identity_verified=false,
  r=>r.result_observations[0].data.results[0].racer_registration_id='4999',
  r=>r.result.payout_yen_per_100=9999,
  r=>r.result_observation_rejections[0].reason='RESULT_ROSTER_MISMATCH',
  r=>r.prediction.persisted_at='2030-04-01T10:00:00+09:00',
  r=>r.saved_schedule_cutoff_variants=[...r.saved_cutoff_variants],
  r=>r.result_observations.push({...structuredClone(r.result_observations[0]),captured_at:'2030-04-01T11:30:00+09:00',status:'PENDING',data:null})
 ];
 for(const mutate of mutations){const raw=reconciled();mutate(raw.records[0]);assert.throws(()=>M.parse(raw));}
});

test('unknown algorithm versions retain separate bound source-code identities for budgets',()=>{
 const raw=fixture(),row=raw.records[0];
 Object.assign(row.prediction,{model_version:null,source_code_commit:'1'.repeat(40),artifact_id:17,original_json_sha256:'2'.repeat(64)});
 row.comparison_predictions=[{...structuredClone(row.prediction),source_code_commit:'3'.repeat(40),artifact_id:18,original_json_sha256:'4'.repeat(64)}];
 const before=JSON.stringify(raw),r=M.parse(raw).records[0],groups=M.modelGroups([r]);
 assert.equal(groups.length,2);assert.equal(new Set(groups.map(g=>g.code_identity)).size,2);
 assert.ok(M.candidates(r).every(p=>p.model_version===null),'a source commit is not an invented algorithm version');
 for(const g of groups){const p=P.pick(r,g);assert.equal(M.codeIdentity(p),g.code_identity);assert.equal(P.simulate([r],g,800).spent,600);}
 assert.equal(M.eligiblePrediction(r,r.prediction),false);assert.equal(JSON.stringify(raw),before);
});

test('code-only identity requires its saved artifact JSON and time binding',()=>{
 for(const field of ['artifact_id','original_json_sha256','persisted_at','source_code_commit']){
  const raw=fixture(),p=raw.records[0].prediction;Object.assign(p,{model_version:null,source_code_commit:'1'.repeat(40),artifact_id:17,original_json_sha256:'2'.repeat(64)});delete p[field];
  const r=M.parse(raw).records[0],g=M.modelGroups([r])[0];assert.equal(M.codeIdentity(r.prediction),null);assert.equal(P.simulate([r],g,800).spent,0);
 }
 const raw=fixture();raw.records[0].prediction.source_code_commit='not-a-commit';assert.throws(()=>M.parse(raw));
});

test('real versions stay preferred and history stability does not cross code-only commits',()=>{
 const raw=fixture(),r=raw.records[0],p=r.prediction;Object.assign(p,{model_version:null,variant:'HISTORY_BASELINE',source_code_commit:'1'.repeat(40),artifact_id:17,original_json_sha256:'2'.repeat(64)});
 r.comparison_predictions=[{...structuredClone(p),variant:'HISTORY_ADDED',source_code_commit:'3'.repeat(40),artifact_id:18,original_json_sha256:'4'.repeat(64)},
  {...structuredClone(p),model_id:'independent-peer',model_version:'v1',source_code_commit:'5'.repeat(40)}];
 const parsed=M.parse(raw).records[0],a=P.allocate(parsed,parsed.prediction,1000);
 assert.ok(a.tickets.every(t=>t.stableFamilies===0),'different saved code commits do not establish history stability');
 assert.equal(a.stake,1000);assert.equal(M.codeIdentity(parsed.comparison_predictions[1]),null,'the actual saved model version remains the identity');
});
