// Safety gate: model findings are only advisory until grounded.
// Require actual new-side added line and a verbatim quoted code excerpt.
// This does NOT prove the code is vulnerable, secure, or formally approved.
const HUNK = /^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/;
const DIFF = /^diff --git a\/(.+) b\/(.+)$/;
const QUOTED = /`([^`]{12,200})`|'([^']{12,200})'|"([^"]{12,200})"/g;

export function anchorAudit(findings, patch) {
  if (!Array.isArray(findings) || findings.length > 20 ||
      typeof patch !== "string" || !patch || patch.length > 150000)
    throw Error("INVALID_ANCHOR_INPUT");
  const additions=new Map();
  let path=null,current=null;
  for (const row of patch.split("\n")) {
    const file=DIFF.exec(row);
    if (file) {
      if (file[1] !== file[2] || additions.has(file[1])) throw Error("UNMATCHED_PATCH_PATH");
      path=file[1];additions.set(path,new Map());current=null;continue;
    }
    const hunk=HUNK.exec(row);
    if (hunk) {
      if (path===null)throw Error("HUNK_WITHOUT_PATH");
      current=Number(hunk[1]);
      if (!Number.isSafeInteger(current)||current<0)throw Error("INVALID_HUNK_LINE");
      continue;
    }
    if (current===null||path===null)continue;
    if(row.startsWith("+")&&!row.startsWith("+++")){
      additions.get(path).set(current,row.slice(1));current++;
    } else if(row.startsWith(" "))current++;
    else if(row.startsWith("-")||row.startsWith("\\")||row.startsWith("#")){ /* source old line or metadata */ }
    else if(row)throw Error("INVALID_PATCH_ROW");
  }
  const checks=findings.map(f=>{
    const code=additions.get(f?.path)?.get(f?.line);
    if(typeof code!=="string"||typeof f.evidence!=="string")
      return {path:f?.path??null,line:f?.line??null,anchored:false,reason:"missing_added_line"};
    const snippets=[...f.evidence.matchAll(QUOTED)].map(x=>x[1]||x[2]||x[3]);
    const anchored=snippets.some(snippet=>code.includes(snippet));
    return {path:f.path,line:f.line,anchored,reason:anchored?"verbatim_added_code":"missing_exact_code_quote"};
  });
  return {complete:checks.every(x=>x.anchored),grounded:checks.filter(x=>x.anchored).length,
    total:checks.length,checks};
}
export function holdUngroundedAdvisory(result, patch) {
  if(!result||!["CHANGES_REQUESTED","NO_ACTIONABLE_FINDINGS","INCONCLUSIVE","BLOCKED"].includes(result.status))
    throw Error("INVALID_AI09_REVIEW_STATUS");
  if(result.status!=="CHANGES_REQUESTED")return result;
  const audit=anchorAudit(result.findings,patch);
  if(audit.complete)return result;
  return {...result,status:"INCONCLUSIVE",blockers:["review_chunk_inconclusive"]};
}
