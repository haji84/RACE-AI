import test from "node:test";
import assert from "node:assert/strict";
import { plan, recordFailure, isVerifiedDone, validateRequirements, saveState } from "../scripts/completion-controller.mjs";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const ev = (sha, issuer="machine") => ({verified:true,issuer,sha,reference:"run/123"});
const base = () => ({
  catalog_scope:"pilot_only", main_sha:"abc",
  requirements:[
    {id:"data",priority:"P0",depends_on:[],acceptance:["unit","integration","runtime"],integrated_sha:null,evidence:{}},
    {id:"prediction",priority:"P0",depends_on:["data"],acceptance:["unit","integration","runtime"],integrated_sha:null,evidence:{}},
    {id:"ui",priority:"P1",depends_on:["data"],acceptance:["unit","integration","runtime"],integrated_sha:null,evidence:{}}
  ],
  pull_requests:[
    {number:1,head_ref:"feature/data",head_sha:"d1",base_ref:"main",draft:true,mergeable:true,ci:"success",verified_head:"d1",independent_review:true},
    {number:2,head_ref:"feature/ui",head_sha:"u1",base_ref:"feature/data",draft:false,mergeable:true,ci:"success",verified_head:"u1",independent_review:true}
  ]
});
test("dependency critical-path prioritization and stacked PR are blocked", () => {
  const p = plan(base());
  assert.equal(p.next_requirements[0].id, "data");
  assert.equal(p.pull_requests[1].parent, 1);
  assert.ok(p.pull_requests[1].reasons.includes("STACKED_ON_OPEN_PR_1"));
  assert.equal(p.product_completion_claim_allowed,false);
});
test("cannot count AI assertions or stale evidence as completed", () => {
  const s=base(); const r=s.requirements[0]; r.integrated_sha="abc";
  r.evidence={unit:ev("abc"),integration:ev("abc","ai"),runtime:ev("abc")};
  assert.equal(isVerifiedDone(r,"abc"),false);
  r.evidence.integration=ev("old");
  assert.equal(isVerifiedDone(r,"abc"),false);
  r.evidence.integration=ev("abc","human");
  assert.equal(isVerifiedDone(r,"abc"),true);
  assert.equal(plan(s).verified_complete,1);
});
test("CI failure retries capped by method; durable restart resumes", () => {
  const e={type:"CI_FAILED",task_id:"data",signature:"job/test:exit1",method:"fix-a"};
  let s={attempts:{}};
  for(let n=1;n<=3;n++){
    const r=recordFailure(s,e);s=r.state;
    assert.equal(r.action,n<3?"DIAGNOSE_AND_RETEST":"REPLAN_REQUIRED");
  }
  const path=join(mkdtempSync(join(tmpdir(),"completion-pilot-")),"state.json");
  saveState(path,s);
  const resumed=recordFailure(JSON.parse(readFileSync(path,"utf8")),{type:"RESTART"});
  assert.equal(resumed.action,"RESUME_FROM_DURABLE_STATE");
  assert.equal(plan(base(),resumed.state).next_requirements[0].status,"REPLAN_REQUIRED");
  assert.equal(recordFailure(s,{...e,method:"fix-b"}).state.attempts.data.count,1);
});
test("conflict triggers replan and never creates merge authority", () => {
  const s=base();s.pull_requests[0].draft=false;s.pull_requests[0].mergeable=false;
  const p=plan(s);
  assert.ok(p.pull_requests[0].reasons.includes("MERGEABILITY_NOT_PROVEN"));
  const o=recordFailure({attempts:{}},{type:"PR_CONFLICT",task_id:"data",signature:"overlap",method:"rebase"});
  assert.equal(o.action,"DIAGNOSE_AND_RETEST");
  assert.equal(p.autonomous_merge_enabled,false);
});
test("invalid or cyclic dependency fails closed", () => {
  const s=base();s.requirements[0].depends_on=["prediction"];
  assert.throws(()=>validateRequirements(s.requirements),/cyclic/);
  const x=base(); x.pull_requests[0].base_ref="feature/ui";
  assert.throws(()=>plan(x),/cyclic PR/);
});
