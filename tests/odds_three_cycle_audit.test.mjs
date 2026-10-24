import test from "node:test";
import assert from "node:assert/strict";
import {auditThreeCycles} from "../race_ai/odds_three_cycle_audit.mjs";
const hash="b".repeat(64);
function fiction(){
 const initial=Date.parse("2030-01-15T00:40:00.000Z");
 const source_attempts=[],safari_receipts=[];
 for(let i=0;i<3;i++){
  const t=initial+i*61_000,r=new Date(t+1200).toISOString();
  source_attempts.push({
   race_id:"20300115-01-03",attempt_at:new Date(t).toISOString(),
   finished_at:new Date(t+1300).toISOString(),
   server_received_at:r,source_published_at:new Date(t-10_000).toISOString(),
   snapshot_sha256:hash,d1_readback_sha256:hash,
   quoted_count:120,ticket_count:120,status:"D1_SAVED_SHA_VERIFIED"
  });
  safari_receipts.push({
   race_id:"20300115-01-03",trigger:"timer",ok:true,
   ingested_at:r,browser_at:new Date(t+2500).toISOString()
  });
 }
 return {schema:"RACE_AI_ODDS_THREE_CYCLE_AUDIT_V1",race_id:"20300115-01-03",
  cutoff_at:"2030-01-15T01:30:00Z",official_cutoff_verified:true,
  rights_confirmed:true,rights_evidence_ref:"synthetic-policy-test-only",
  shared_free_quota_verified:true,source_attempts,safari_receipts};
}
test("three source,D1,Safari three-cycle contract is explicitly untrusted metadata",()=>{
 const verdict=auditThreeCycles(fiction());
 assert.equal(verdict.status,"METADATA_CONTRACT_PASS_NEEDS_INDEPENDENT_ATTESTATION");
 assert.deepEqual(verdict.blockers,[]);
 assert.deepEqual(verdict.observed,{source_cycles:3,saved_cycles:3,browser_linked_cycles:3});
 assert.match(verdict.warning,/not proof/);
});
test("one manual shot or three browser-only refreshes cannot claim upstream E2E",()=>{
 const one=fiction();one.source_attempts=one.source_attempts.slice(0,1);
 assert.ok(auditThreeCycles(one).blockers.includes("FEWER_THAN_THREE_SOURCE_CYCLES"));
 const browserOnly=fiction();browserOnly.source_attempts=[];
 assert.equal(auditThreeCycles(browserOnly).status,"HOLD");
 const manual=fiction();manual.safari_receipts.forEach(x=>x.trigger="manual");
 assert.ok(auditThreeCycles(manual).blockers.includes("THREE_SAFARI_D1_LINKED_RECEIPTS_NOT_PROVEN"));
});
test("source rights/quota/official cutoff must remain independent gates",()=>{
 const doc=fiction();doc.rights_confirmed=false;doc.shared_free_quota_verified=false;
 doc.official_cutoff_verified=false;
 const blockers=auditThreeCycles(doc).blockers;
 assert.ok(blockers.includes("UPSTREAM_RIGHTS_UNVERIFIED"));
 assert.ok(blockers.includes("ACCOUNT_FREE_USAGE_UNVERIFIED"));
 assert.ok(blockers.includes("OFFICIAL_CUTOFF_UNVERIFIED"));
});
test("bad SHA, too-short cadence, post-cutoff writes and unchanged-only snapshots block",()=>{
 const bad=fiction();bad.source_attempts[1].d1_readback_sha256="c".repeat(64);
 assert.ok(auditThreeCycles(bad).blockers.includes("D1_READBACK_SHA_MISMATCH"));
 const early=fiction();early.source_attempts[1].attempt_at=new Date(Date.parse(early.source_attempts[0].attempt_at)+40_000).toISOString();
 assert.ok(auditThreeCycles(early).blockers.includes("SOURCE_CADENCE_BELOW_55_SECONDS"));
 const cutoff=fiction();cutoff.cutoff_at="2030-01-15T00:40:01Z";
 assert.ok(auditThreeCycles(cutoff).blockers.includes("INVALID_SOURCE_RECEIPT"));
 const same=fiction();same.source_attempts[1].status="SOURCE_UNCHANGED";
 assert.ok(auditThreeCycles(same).blockers.includes("THREE_D1_SNAPSHOT_WRITES_NOT_PROVEN"));
});
test("browser timestamp must correspond to D1 stored delivery not an old stale receipt",()=>{
 const wrong=fiction();wrong.safari_receipts[1].ingested_at="2030-01-15T00:00:00Z";
 assert.ok(auditThreeCycles(wrong).blockers.includes("THREE_SAFARI_D1_LINKED_RECEIPTS_NOT_PROVEN"));
});

test("D1 readback finishing after cutoff is invalid",()=>{
 const doc=fiction();
 doc.cutoff_at=new Date(Date.parse(doc.source_attempts[2].server_received_at)+50).toISOString();
 assert.ok(auditThreeCycles(doc).blockers.includes("INVALID_SOURCE_RECEIPT"));
});
