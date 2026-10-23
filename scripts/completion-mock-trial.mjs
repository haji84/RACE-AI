// OFFLINE MOCK TRIAL ONLY. No AI backend, network, repository writes, deployment or real races.
import { readFileSync, writeFileSync, appendFileSync, renameSync, mkdirSync, existsSync, openSync, closeSync, unlinkSync } from "node:fs";
import { join, resolve } from "node:path";
import { hostname } from "node:os";
import { createHash, randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { plan } from "./completion-controller.mjs";

const ids = ["fixture-a", "fixture-b"];
const identity = createHash("sha256").update(readFileSync(fileURLToPath(import.meta.url))).digest("hex");
function atomic(file, value) {
  const tmp=file+"."+randomUUID()+".tmp";
  writeFileSync(tmp, JSON.stringify(value,null,2)+"\n",{flag:"wx",mode:0o600});
  renameSync(tmp,file);
}
function read(file) { return JSON.parse(readFileSync(file,"utf8")); }
function acquire(file) {
  try {
    const fd=openSync(file,"wx",0o600);
    writeFileSync(fd,JSON.stringify({pid:process.pid,host:hostname()}));
    closeSync(fd);
  } catch(e) {
    if(e.code!=="EEXIST") throw e;
    const recovery=file+".recovery";
    const guard=openSync(recovery,"wx",0o600);
    try {
      const owner=read(file); // Re-read while holding the recovery guard.
      if(owner.host!==hostname() || !Number.isSafeInteger(owner.pid) || owner.pid<=0) throw Error("LOCK_OWNER_UNCERTAIN");
      try { process.kill(owner.pid,0); throw Error("ALREADY_RUNNING"); }
      catch(check) { if(check.code!=="ESRCH") throw check; }
      // Local-host trial only. Uncertain or abandoned recovery locks fail closed.
      unlinkSync(file);
      const fd=openSync(file,"wx",0o600);
      writeFileSync(fd,JSON.stringify({pid:process.pid,host:hostname()}));
      closeSync(fd);
    } finally { closeSync(guard); unlinkSync(recovery); }
  }
}
function validate(state) {
  if(state.kind!=="OFFLINE_MOCK_CONTINUATION_V1" || state.runner_sha256!==identity ||
    state.real_ai_development!==false || !Array.isArray(state.completed) ||
    state.completed.some((id,i)=>id!==ids[i]) || state.completed.length>ids.length ||
    (state.active!==null && (!state.active || state.active.task_id!==ids[state.completed.length] ||
      state.active.attempt_id!=="mock-"+state.active.task_id))) throw Error("STATE_INVALID_OR_STALE");
}
function expected(task) { return {task_id:task,attempt_id:"mock-"+task,runner_sha256:identity,result:task+":accepted",synthetic:true}; }
function verify(receipt, task) { return JSON.stringify(receipt)===JSON.stringify(expected(task)); }
function choose(state) {
  const requirements=ids.map((id,index)=>({
    id, priority:"P0", depends_on:index?[ids[index-1]]:[], acceptance:["mock_result"],
    integrated_sha:state.completed.includes(id)?"fixture-only":null,
    evidence:state.completed.includes(id)?{mock_result:{verified:true,issuer:"machine",sha:"fixture-only",reference:"synthetic-receipt:"+id}}:{}
  }));
  const report=plan({catalog_scope:"pilot_only",main_sha:"fixture-only",requirements,pull_requests:[]});
  if(report.product_completion_claim_allowed || report.autonomous_merge_enabled) throw Error("UNSAFE_PRODUCT_CLAIM");
  return report.next_requirements.find(x=>x.status==="READY_FOR_VERIFICATION_OR_IMPLEMENTATION")?.id;
}
function main() {
  const args=process.argv.slice(2);
  if(args.length!==2 && args.length!==4) throw Error("usage: --state-dir PATH [--crash-after-result fixture-a]");
  if(args[0]!=="--state-dir" || !args[1] || (args.length===4 && (args[2]!=="--crash-after-result" || !ids.includes(args[3])))) throw Error("invalid arguments");
  const dir=resolve(args[1]); mkdirSync(dir,{recursive:true});
  const lock=join(dir,"owner.lock"); acquire(lock);
  try {
    const stateFile=join(dir,"state.json");
    let state=existsSync(stateFile)?read(stateFile):{kind:"OFFLINE_MOCK_CONTINUATION_V1",runner_sha256:identity,real_ai_development:false,completed:[],active:null};
    validate(state);
    // Completed checkpoints are claims, not evidence: verify their receipts again.
    for (const completed of state.completed) {
      const receipt=join(dir,"result-"+completed+".json");
      if(!existsSync(receipt) || !verify(read(receipt),completed)) throw Error("COMPLETED_EVIDENCE_MISMATCH");
    }
    for(let cycle=0;cycle<ids.length+1;cycle++) {
      let task=state.active?.task_id;
      let newlyStarted=false;
      if(!task) {
        task=choose(state);
        if(!task) {
          process.stdout.write(JSON.stringify({kind:state.kind,completed:state.completed,real_ai_development:false,network_calls:0,deployments:0})+"\n");
          return;
        }
        state.active={task_id:task,attempt_id:"mock-"+task};
        atomic(stateFile,state);
        newlyStarted=true;
      }
      const resultFile=join(dir,"result-"+task+".json");
      if(!existsSync(resultFile)) {
        if(!newlyStarted) throw Error("UNKNOWN_OUTCOME_DO_NOT_REDISPATCH");
        // The executor is deliberately a fixed synthetic local-file operation.
        appendFileSync(join(dir,"effects.jsonl"),JSON.stringify({task_id:task,attempt_id:"mock-"+task})+"\n",{mode:0o600});
        atomic(resultFile,expected(task));
        if(args[3]===task) process.exit(43); // Real subprocess exit before completion checkpoint.
      }
      if(!verify(read(resultFile),task)) throw Error("RESULT_EVIDENCE_MISMATCH");
      state.completed.push(task); state.active=null; atomic(stateFile,state);
    }
    throw Error("CYCLE_LIMIT");
  } finally { unlinkSync(lock); }
}
try { main(); } catch(e) { process.stderr.write(e.message+"\n"); process.exitCode=1; }
