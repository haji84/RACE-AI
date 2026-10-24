import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync, unlinkSync } from "node:fs";
import { tmpdir, hostname } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
const script = resolve("scripts/completion-mock-trial.mjs");
test("mock continuation trial is available", () => {
  assert.ok(existsSync(script), "missing mock continuation runner");
});
test("mock tasks continue without another human instruction and rerun does not duplicate", { skip: !existsSync(script) }, () => {
  const dir=mkdtempSync(join(tmpdir(),"race-mock-trial-"));
  try {
    const run=()=>spawnSync(process.execPath,[script,"--state-dir",dir],{encoding:"utf8"});
    const first=run(); assert.equal(first.status,0,first.stderr);
    const state=JSON.parse(readFileSync(join(dir,"state.json"),"utf8"));
    assert.deepEqual(state.completed,["fixture-a","fixture-b"]);
    assert.equal(state.real_ai_development,false);
    const again=run(); assert.equal(again.status,0,again.stderr);
    assert.equal(readFileSync(join(dir,"effects.jsonl"),"utf8").trim().split("\n").length,2);
  } finally { rmSync(dir,{recursive:true,force:true}); }
});
test("hard exit resumes from saved result and automatically reaches the next task", { skip: !existsSync(script) }, () => {
  const dir=mkdtempSync(join(tmpdir(),"race-mock-crash-"));
  try {
    const interrupted=spawnSync(process.execPath,[script,"--state-dir",dir,"--crash-after-result","fixture-a"],{encoding:"utf8"});
    assert.equal(interrupted.status,43,interrupted.stderr);
    const mid=JSON.parse(readFileSync(join(dir,"state.json"),"utf8"));
    assert.equal(mid.active.task_id,"fixture-a");
    const resumed=spawnSync(process.execPath,[script,"--state-dir",dir],{encoding:"utf8"});
    assert.equal(resumed.status,0,resumed.stderr);
    const state=JSON.parse(readFileSync(join(dir,"state.json"),"utf8"));
    assert.deepEqual(state.completed,["fixture-a","fixture-b"]);
    assert.equal(readFileSync(join(dir,"effects.jsonl"),"utf8").trim().split("\n").length,2);
  } finally { rmSync(dir,{recursive:true,force:true}); }
});

test("uncertain executor outcome is not redispatched", { skip: !existsSync(script) }, () => {
 const dir=mkdtempSync(join(tmpdir(),"race-mock-unknown-"));
 try {
  assert.equal(spawnSync(process.execPath,[script,"--state-dir",dir,"--crash-after-result","fixture-a"]).status,43);
  unlinkSync(join(dir,"result-fixture-a.json"));
  const resumed=spawnSync(process.execPath,[script,"--state-dir",dir],{encoding:"utf8"});
  assert.equal(resumed.status,1); assert.match(resumed.stderr,/UNKNOWN_OUTCOME_DO_NOT_REDISPATCH/);
  assert.equal(readFileSync(join(dir,"effects.jsonl"),"utf8").trim().split("\n").length,1);
 } finally { rmSync(dir,{recursive:true,force:true}); }
});
test("tampered result is not completion evidence", { skip: !existsSync(script) }, () => {
 const dir=mkdtempSync(join(tmpdir(),"race-mock-tamper-"));
 try {
  assert.equal(spawnSync(process.execPath,[script,"--state-dir",dir,"--crash-after-result","fixture-a"]).status,43);
  writeFileSync(join(dir,"result-fixture-a.json"),'{"synthetic":true}');
  const resumed=spawnSync(process.execPath,[script,"--state-dir",dir],{encoding:"utf8"});
  assert.equal(resumed.status,1); assert.match(resumed.stderr,/RESULT_EVIDENCE_MISMATCH/);
  assert.deepEqual(JSON.parse(readFileSync(join(dir,"state.json"),"utf8")).completed,[]);
 } finally { rmSync(dir,{recursive:true,force:true}); }
});
test("live owner blocks a second executor", { skip: !existsSync(script) }, () => {
 const dir=mkdtempSync(join(tmpdir(),"race-mock-owner-"));
 try {
  writeFileSync(join(dir,"owner.lock"),JSON.stringify({pid:process.pid,host:hostname()}));
  const other=spawnSync(process.execPath,[script,"--state-dir",dir],{encoding:"utf8"});
  assert.equal(other.status,1); assert.match(other.stderr,/ALREADY_RUNNING/);
  assert.equal(existsSync(join(dir,"effects.jsonl")),false);
 } finally { rmSync(dir,{recursive:true,force:true}); }
});

for (const mode of ["missing","tampered"]) {
 test("completed "+mode+" receipt cannot be trusted on restart", () => {
  const dir=mkdtempSync(join(tmpdir(),"race-mock-completed-"));
  try {
   assert.equal(spawnSync(process.execPath,[script,"--state-dir",dir]).status,0);
   const receipt=join(dir,"result-fixture-a.json");
   if(mode==="missing") unlinkSync(receipt); else writeFileSync(receipt,'{"synthetic":true}');
   const resumed=spawnSync(process.execPath,[script,"--state-dir",dir],{encoding:"utf8"});
   assert.equal(resumed.status,1); assert.match(resumed.stderr,/COMPLETED_EVIDENCE_MISMATCH/);
   assert.equal(readFileSync(join(dir,"effects.jsonl"),"utf8").trim().split("\n").length,2);
  } finally { rmSync(dir,{recursive:true,force:true}); }
 });
}
