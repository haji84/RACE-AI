import { readFileSync, writeFileSync, renameSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { pathToFileURL } from "node:url";

export function validateRequirements(requirements) {
  if (!Array.isArray(requirements) || requirements.length === 0) throw Error("requirements must be a non-empty array");
  const byId = new Map();
  for (const item of requirements) {
    if (!item || typeof item.id !== "string" || !item.id || byId.has(item.id)) throw Error("invalid or duplicate requirement id");
    if (!Array.isArray(item.depends_on) || !Array.isArray(item.acceptance) || item.acceptance.length === 0) throw Error("requirement lacks dependencies/acceptance");
    byId.set(item.id, item);
  }
  const visiting = new Set(), visited = new Set();
  function walk(id) {
    if (!byId.has(id)) throw Error("missing dependency: " + id);
    if (visiting.has(id)) throw Error("cyclic requirement dependency: " + id);
    if (visited.has(id)) return;
    visiting.add(id);
    for (const dep of byId.get(id).depends_on) walk(dep);
    visiting.delete(id); visited.add(id);
  }
  for (const id of byId.keys()) walk(id);
  return byId;
}

export function isVerifiedDone(requirement, mainSha) {
  if (typeof mainSha !== "string" || !mainSha || requirement.integrated_sha !== mainSha) return false;
  return requirement.acceptance.every(kind => {
    const e = requirement.evidence?.[kind];
    return e?.verified === true && (e.issuer === "machine" || e.issuer === "human") &&
      e.sha === mainSha && typeof e.reference === "string" && e.reference.length > 0;
  });
}

export function recordFailure(state, event) {
  if (!event || !["CI_FAILED", "PR_CONFLICT", "RESTART"].includes(event.type)) throw Error("unknown event");
  const next = structuredClone(state || { attempts: {} });
  next.attempts ||= {};
  if (event.type === "RESTART") return { state: next, action: "RESUME_FROM_DURABLE_STATE" };
  if (!event.task_id || !event.signature || !event.method) throw Error("failure event incomplete");
  const old = next.attempts[event.task_id];
  const fingerprint = [event.type, event.signature, event.method].join("|");
  const count = old?.fingerprint === fingerprint ? old.count + 1 : 1;
  next.attempts[event.task_id] = { fingerprint, count, last_event: event.type };
  return { state: next, action: count >= 3 ? "REPLAN_REQUIRED" : "DIAGNOSE_AND_RETEST" };
}

export function plan(snapshot, state = {}) {
  if (!snapshot || typeof snapshot.main_sha !== "string" || !snapshot.main_sha) throw Error("missing main sha");
  const byId = validateRequirements(snapshot.requirements);
  const done = new Set(snapshot.requirements.filter(x => isVerifiedDone(x, snapshot.main_sha)).map(x => x.id));
  const children = new Map([...byId.keys()].map(id => [id, new Set()]));
  for (const req of snapshot.requirements) for (const dep of req.depends_on) children.get(dep).add(req.id);
  function reachable(id, seen = new Set()) {
    for (const child of children.get(id)) if (!seen.has(child)) { seen.add(child); reachable(child, seen); }
    return seen.size;
  }
  const pending = snapshot.requirements.filter(x => !done.has(x.id)).map(x => {
    const unmet = x.depends_on.filter(id => !done.has(id));
    const incident = state.attempts?.[x.id];
    return {
      id: x.id,
      status: incident?.count >= 3 ? "REPLAN_REQUIRED" : unmet.length ? "WAITING_DEPENDENCY" : "READY_FOR_VERIFICATION_OR_IMPLEMENTATION",
      unmet, priority_score: reachable(x.id) * 100 + (x.priority === "P0" ? 50 : x.priority === "P1" ? 20 : 0)
    };
  }).sort((a,b) => b.priority_score-a.priority_score || a.id.localeCompare(b.id));
  const prs = Array.isArray(snapshot.pull_requests) ? snapshot.pull_requests : [];
  const branchToPr = new Map(prs.map(pr => [pr.head_ref, pr.number]));
  if (branchToPr.size !== prs.length) throw Error("duplicate PR head branch");
  const resultPrs = prs.map(pr => {
    const parent = branchToPr.get(pr.base_ref);
    const reasons = [];
    if (parent !== undefined) reasons.push("STACKED_ON_OPEN_PR_" + parent);
    else if (pr.base_ref !== "main") reasons.push("UNVERIFIED_BASE_BRANCH");
    if (pr.draft !== false) reasons.push("DRAFT");
    if (pr.mergeable !== true) reasons.push("MERGEABILITY_NOT_PROVEN");
    if (pr.ci !== "success" || pr.verified_head !== pr.head_sha) reasons.push("EXACT_HEAD_CI_NOT_PROVEN");
    if (pr.independent_review !== true) reasons.push("INDEPENDENT_REVIEW_MISSING");
    if (pr.human_gate_required === true) reasons.push("HUMAN_GATE");
    return { number: pr.number, parent: parent ?? null, status: reasons.length ? "BLOCKED" : "REVIEW_READY_ONLY", reasons };
  });
  const byNumber = new Map(resultPrs.map(pr => [pr.number, pr]));
  function checkPrCycle(pr, stack=new Set()) {
    if (stack.has(pr.number)) throw Error("cyclic PR dependency");
    if (pr.parent === null) return;
    stack.add(pr.number);
    checkPrCycle(byNumber.get(pr.parent), stack);
    stack.delete(pr.number);
  }
  for (const pr of resultPrs) checkPrCycle(pr);
  return {
    catalog_scope: snapshot.catalog_scope || "pilot_only",
    verified_complete: done.size,
    total_requirements_in_catalog: snapshot.requirements.length,
    product_completion_claim_allowed: snapshot.catalog_scope === "complete_product" && done.size === snapshot.requirements.length,
    next_requirements: pending,
    pull_requests: resultPrs,
    read_only: true,
    autonomous_merge_enabled: false
  };
}

export function saveState(file, state) {
  mkdirSync(dirname(file), { recursive: true });
  const temp = file + ".tmp";
  writeFileSync(temp, JSON.stringify(state, null, 2) + "\n", { mode: 0o600 });
  renameSync(temp, file);
}

async function fromGithub(catalog, repo, token) {
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repo)) throw Error("invalid repository");
  const headers = { "Accept": "application/vnd.github+json", "User-Agent": "race-ai-completion-controller" };
  if (token) headers.Authorization = "Bearer " + token;
  async function get(path) {
    const r = await fetch("https://api.github.com/repos/" + repo + path, { headers });
    if (!r.ok) throw Error("GitHub read failed " + r.status + " (" + path + ")");
    return r.json();
  }
  const latest = await get("/commits/main");
  const prs = [];
  for (let page=1; page<=10; page++) {
    const batch = await get("/pulls?state=open&per_page=100&page=" + page);
    prs.push(...batch.map(p => ({
      number:p.number, head_ref:p.head.ref, head_sha:p.head.sha, base_ref:p.base.ref,
      draft:p.draft, mergeable:p.mergeable, ci:"unknown", verified_head:null,
      independent_review:false, human_gate_required:false
    })));
    if (batch.length < 100) break;
    if (page === 10) throw Error("PR pagination exceeded; fail closed");
  }
  return { ...catalog, main_sha:latest.sha, pull_requests:prs };
}

async function cli() {
  const args = process.argv.slice(2);
  function option(flag, fallback) {
    const idx = args.indexOf(flag);
    return idx < 0 ? fallback : args[idx+1];
  }
  const catalog = JSON.parse(readFileSync(option("--catalog", "config/completion-pilot.json"), "utf8"));
  const stateFile = option("--state", null);
  let state = stateFile ? JSON.parse(readFileSync(stateFile, "utf8")) : { attempts:{} };
  const eventFile = option("--event", null);
  if (eventFile) {
    const outcome = recordFailure(state, JSON.parse(readFileSync(eventFile, "utf8")));
    state = outcome.state;
    if (stateFile) saveState(stateFile, state);
  }
  const snapshotFile = option("--snapshot", null);
  const snapshot = snapshotFile ? JSON.parse(readFileSync(snapshotFile, "utf8")) :
    args.includes("--github") ? await fromGithub(catalog, option("--repository", process.env.GITHUB_REPOSITORY || "haji84/RACE-AI"), process.env.GITHUB_TOKEN) :
    null;
  if (!snapshot) throw Error("provide --snapshot or --github; missing evidence is never success");
  process.stdout.write(JSON.stringify(plan(snapshot, state), null, 2) + "\n");
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  cli().catch(e => { process.stderr.write(e.message + "\n"); process.exitCode=1; });
}
