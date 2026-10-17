import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { recordFailure } from "../scripts/completion-controller.mjs";

function node(code, cwd) {
  return spawnSync(process.execPath, ["--input-type=module", "-e", code], { cwd, encoding:"utf8" });
}
function git(cwd,...args) {
  const result=spawnSync("git",args,{cwd,encoding:"utf8"});
  return result;
}
function checked(result, label) {
  assert.equal(result.status, 0, label+": "+result.stderr);
}
test("real subprocess hard-exit leaves checkpoint for independent restarted process", () => {
  const dir=mkdtempSync(join(tmpdir(),"race-completion-restart-"));
  try {
    const stateFile=join(dir,"checkpoint.json");
    const moduleUrl=pathToFileURL(join(process.cwd(),"scripts/completion-controller.mjs")).href;
    const producer=node(`import {saveState} from ${JSON.stringify(moduleUrl)};saveState(${JSON.stringify(stateFile)}, {attempts:{work:{fingerprint:"CI_FAILED|oops|first",count:2,last_event:"CI_FAILED"}}});process.exit(43)`,dir);
    assert.equal(producer.status,43,"intentional simulated crash must actually terminate process");
    const consumer=node(`import {readFileSync} from "node:fs";import {recordFailure,saveState} from ${JSON.stringify(moduleUrl)};const s=JSON.parse(readFileSync(${JSON.stringify(stateFile)},"utf8"));const r=recordFailure(s,{type:"RESTART"});if(r.action!=="RESUME_FROM_DURABLE_STATE"||r.state.attempts.work.count!==2)process.exit(8);saveState(${JSON.stringify(stateFile)},r.state)`,dir);
    checked(consumer,"restart must restore earlier checkpoint");
    assert.equal(JSON.parse(readFileSync(stateFile,"utf8")).attempts.work.count,2);
  } finally { rmSync(dir,{recursive:true,force:true}); }
});
test("real failing CI subprocess yields failure evidence; changed method rerun succeeds", () => {
  const dir=mkdtempSync(join(tmpdir(),"race-completion-ci-"));
  try {
    const failed=node("process.stderr.write('KNOWN_FAILURE\\n');process.exit(37)",dir);
    assert.equal(failed.status,37);
    assert.match(failed.stderr,/KNOWN_FAILURE/);
    let state={ attempts:{} };
    for(let n=1;n<=3;n++){
      const r=recordFailure(state,{type:"CI_FAILED",task_id:"ci-fixture",signature:"exit37",method:"retry-identical"});
      state=r.state;
      assert.equal(r.action,n===3?"REPLAN_REQUIRED":"DIAGNOSE_AND_RETEST");
    }
    const alternative=node("process.stdout.write('RECOVERED\\n');process.exit(0)",dir);
    checked(alternative,"changed recovery strategy");
    assert.match(alternative.stdout,/RECOVERED/);
    assert.equal(recordFailure(state,{type:"CI_FAILED",task_id:"ci-fixture",signature:"exit37",method:"alternate"}).state.attempts["ci-fixture"].count,1);
  } finally { rmSync(dir,{recursive:true,force:true}); }
});
test("real git merge conflict is blocked and resolved through a fresh integration branch", () => {
  const dir=mkdtempSync(join(tmpdir(),"race-completion-conflict-"));
  try {
    checked(git(dir,"init","-b","main"),"init");
    checked(git(dir,"config","user.email","completion-test@example.invalid"),"author");
    checked(git(dir,"config","user.name","Completion Test"),"author");
    writeFileSync(join(dir,"policy.txt"),"mode=initial\n");
    checked(git(dir,"add","policy.txt"),"add");
    checked(git(dir,"commit","-m","initial"),"commit");
    checked(git(dir,"checkout","-b","lane-a"),"branch a");
    writeFileSync(join(dir,"policy.txt"),"mode=alpha\n");
    checked(git(dir,"commit","-am","lane-a"),"commit a");
    checked(git(dir,"checkout","main"),"main");
    checked(git(dir,"checkout","-b","lane-b"),"branch b");
    writeFileSync(join(dir,"policy.txt"),"mode=beta\n");
    checked(git(dir,"commit","-am","lane-b"),"commit b");
    checked(git(dir,"checkout","main"),"main");
    checked(git(dir,"merge","--no-ff","--no-edit","lane-a"),"integrate a");
    const conflict=git(dir,"merge","--no-ff","--no-edit","lane-b");
    assert.notEqual(conflict.status,0,"actual git conflicting merge must fail");
    assert.match(readFileSync(join(dir,"policy.txt"),"utf8"),/<{7}/);
    const assessment=recordFailure({attempts:{}},{type:"PR_CONFLICT",task_id:"lane-b",signature:"merge-policy-conflict",method:"merge"});
    assert.equal(assessment.action,"DIAGNOSE_AND_RETEST");
    checked(git(dir,"merge","--abort"),"safe abort");
    checked(git(dir,"checkout","-b","lane-b-replanned"),"new integration branch");
    writeFileSync(join(dir,"policy.txt"),"mode=alpha\nfeature-b=enabled\n");
    checked(git(dir,"add","policy.txt"),"add revised integration");
    checked(git(dir,"commit","-m","lane-b with resolved dependency"),"commit revised");
    checked(git(dir,"checkout","main"),"return to main");
    checked(git(dir,"merge","--no-ff","--no-edit","lane-b-replanned"),"integrate revised");
    assert.equal(readFileSync(join(dir,"policy.txt"),"utf8"),"mode=alpha\nfeature-b=enabled\n");
  } finally { rmSync(dir,{recursive:true,force:true}); }
});
