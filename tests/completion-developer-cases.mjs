// Independent acceptance cases for an isolated controller repair; never changes repository files.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const [candidate,stage]=process.argv.slice(2);
if(!candidate||!['acceptance','reference'].includes(stage))throw Error('CASE_SCOPE_INVALID');
const {isVerifiedDone,plan}=await import(pathToFileURL(candidate));
const make=(reference='run/123')=>({id:'proof',depends_on:[],acceptance:['unit'],integrated_sha:'test-head',evidence:{unit:{verified:true,issuer:'machine',sha:'test-head',reference}}});
assert.equal(isVerifiedDone(make(),'test-head'),true);
assert.equal(isVerifiedDone(make(),'other-head'),false);
const ai=make();ai.evidence.unit.issuer='ai';assert.equal(isVerifiedDone(ai,'test-head'),false);
const missing=make();missing.evidence={};assert.equal(isVerifiedDone(missing,'test-head'),false);
if(stage==='acceptance')for(const acceptance of [[],null,undefined,{},'unit']){
 const r=make();r.acceptance=acceptance;
 assert.equal(isVerifiedDone(r,'test-head'),false,'EMPTY_OR_MALFORMED_ACCEPTANCE_MUST_NOT_COMPLETE');
}
if(stage==='reference'){
 for(const reference of ['', ' ', '\t\n', '\u3000',null,undefined,0,{},[]]){const r=make();r.evidence.unit.reference=reference;assert.equal(isVerifiedDone(r,'test-head'),false,'BLANK_REFERENCE_MUST_NOT_COMPLETE');}
 assert.equal(isVerifiedDone(make(' run/123 '),'test-head'),true);
 const r=make(' '),p=plan({catalog_scope:'pilot_only',main_sha:'test-head',requirements:[r],pull_requests:[]});
 assert.equal(p.verified_complete,0);
 assert.equal(p.product_completion_claim_allowed,false);
}
console.log(JSON.stringify({status:'PASS',stage,candidate,real_product_acceptance:false}));
