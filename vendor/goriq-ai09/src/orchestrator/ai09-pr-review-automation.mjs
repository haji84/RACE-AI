import { createHash } from "node:crypto";
import { Buffer } from "node:buffer";

export const SHA40 = /^[a-f0-9]{40}$/;
const SHA256 = /^[a-f0-9]{64}$/;
const REPO = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
const MAX_FILES = 30;
// Review all changed bytes, but feed the local model only bounded per-file
// segments. Never silently truncate a patch or mark partial review as clean.
const MAX_PATCH_BYTES = 120 * 1024;
const MAX_CHUNK_BYTES = 4 * 1024;
const MAX_CHUNKS = 24;
const ALLOWED = new Set(["NO_ACTIONABLE_FINDINGS", "CHANGES_REQUESTED", "INCONCLUSIVE", "BLOCKED"]);

export function eligibleCiPullRequest({ run, pr, repo, defaultBranch = "main" }) {
  if (!run || !pr || !repo || !REPO.test(repo.full_name ?? "") ||
    run.event !== "pull_request" || run.status !== "completed" || run.name !== "CI" ||
    !Number.isSafeInteger(pr.number) || pr.number <= 0 ||
    pr.state !== "open" || pr.base?.ref !== defaultBranch ||
    pr.base?.repo?.full_name !== repo.full_name || pr.head?.repo?.full_name !== repo.full_name ||
    !SHA40.test(run.head_sha ?? "") || run.head_sha !== pr.head?.sha ||
    !SHA40.test(pr.base.sha ?? "") || run.repository?.id !== repo.id) {
    return false;
  }
  const linked = Array.isArray(run.pull_requests) ? run.pull_requests : [];
  return linked.some(candidate =>
    candidate.number === pr.number &&
    candidate.head?.sha === pr.head.sha &&
    candidate.base?.sha === pr.base.sha &&
    candidate.head?.repo?.id === repo.id &&
    candidate.base?.repo?.id === repo.id
  );
}

export function validCompletedCiRun(run, expected) {
  if (!run || typeof run !== "object" ||
    run.id !== expected.ciRunId || run.name !== "CI" ||
    run.event !== "pull_request" || run.status !== "completed" ||
    !["success", "failure", "cancelled", "timed_out", "neutral", "skipped", "action_required"].includes(run.conclusion) ||
    run.conclusion !== expected.ciConclusion ||
    run.repository?.full_name !== expected.repository ||
    run.head_sha !== expected.headSha ||
    !Array.isArray(run.pull_requests)) return false;
  return run.pull_requests.some(link =>
    link.number === expected.prNumber &&
    link.head?.sha === expected.headSha &&
    link.base?.sha === expected.baseSha &&
    link.head?.repo?.id === run.repository.id &&
    link.base?.repo?.id === run.repository.id
  );
}

export function compareToPatch(compare, baseSha, headSha) {
  if (!SHA40.test(baseSha) || !SHA40.test(headSha) || baseSha === headSha ||
    !compare || !["ahead", "diverged"].includes(compare.status) ||
    !Number.isSafeInteger(compare.ahead_by) || compare.ahead_by < 1 ||
    !Array.isArray(compare.files) || compare.files.length < 1 || compare.files.length > MAX_FILES ||
    (compare.total_commits !== undefined && compare.total_commits > 250)) {
    throw new Error("invalid_or_oversized_comparison");
  }
  const paths = [];
  const chunks = [];
  for (const file of compare.files) {
    const name = file?.filename;
    if (typeof name !== "string" || name.length > 250 || !name.trim() ||
      name.startsWith("-") || name.startsWith("/") || name.includes("\\") ||
      name.split("/").some(part => !part || part === "." || part === "..") ||
      [...name].some(ch => ch.charCodeAt(0) < 32) ||
      typeof file.patch !== "string" || !file.patch.startsWith("@@")) {
      throw new Error("unsafe_or_unreviewable_patch");
    }
    paths.push(name);
    chunks.push("diff --git a/" + name + " b/" + name + "\n" + file.patch);
  }
  if (new Set(paths).size !== paths.length) throw new Error("duplicate_changed_path");
  const patch = chunks.join("\n");
  if (Buffer.byteLength(patch, "utf8") > MAX_PATCH_BYTES) throw new Error("diff_exceeds_local_review_budget");
  return { paths, patch, patchSha256: createHash("sha256").update(patch).digest("hex") };
}

export function compareToReviewChunks(compare, baseSha, headSha) {
  const whole = compareToPatch(compare, baseSha, headSha);
  // Small semantic slices are much faster on GitHub-hosted CPU than a 15 KiB
  // single-model request. These are model inputs only; the canonical full
  // comparison and SHA remain the authority for every review receipt.
  const chunks = [];
  const fileParts = [];
  for (const file of compare.files) {
    const header = "diff --git a/" + file.filename + " b/" + file.filename;
    const lines = file.patch.split("\n");
    const groups = [];
    let section = [], previousHunk = "";
    const buildDisplay = (part, hunk, index) =>
      header + "\n" +
      "# AI09_REVIEW_SLICE " + (index + 1) + " of this file; review only shown additions/deletions\n" +
      (part[0]?.startsWith("@@") ? "" : hunk + "\n") + part.join("\n");
    const flush = () => {
      if (!section.length) return;
      const hunk = groups.length ? groups.at(-1).endingHunk : previousHunk;
      const display = buildDisplay(section, hunk || "@@ continuation @@", groups.length);
      if (Buffer.byteLength(display, "utf8") > MAX_CHUNK_BYTES) throw Error("unreviewable_oversized_line");
      groups.push({source: section.join("\n"), display, endingHunk:previousHunk});
      section = [];
    };
    for (const line of lines) {
      const hunk = line.startsWith("@@") ? line : previousHunk;
      const next = [...section, line];
      // Reserve overhead for the stable synthetic header and hunk context.
      const head = section[0]?.startsWith("@@") ? "" : (hunk || "@@ continuation @@") + "\n";
      const projected = header + "\n# AI09_REVIEW_SLICE " + (groups.length + 1) +
        " of this file; review only shown additions/deletions\n" + head + next.join("\n");
      if (Buffer.byteLength(projected, "utf8") > MAX_CHUNK_BYTES && section.length) flush();
      const one = header + "\n# AI09_REVIEW_SLICE " + (groups.length + 1) +
        " of this file; review only shown additions/deletions\n" + (line.startsWith("@@") ? "" : (hunk || "@@ continuation @@") + "\n") + line;
      if (Buffer.byteLength(one, "utf8") > MAX_CHUNK_BYTES) throw Error("unreviewable_oversized_line");
      section.push(line);
      if (line.startsWith("@@")) previousHunk = line;
    }
    flush();
    const joined = groups.map(g => g.source).join("\n");
    if (joined !== file.patch) throw Error("review_source_line_coverage_mismatch");
    fileParts.push(header + "\n" + joined);
    for (const group of groups) {
      chunks.push({paths:[file.filename], patch:group.display, source:group.source,
        fileIndex:fileParts.length - 1});
    }
  }
  if (!chunks.length || chunks.length > MAX_CHUNKS ||
      chunks.some(c => Buffer.byteLength(c.patch, "utf8") > MAX_CHUNK_BYTES)) {
    throw Error("review_chunk_budget_exhausted");
  }
  // Every source byte belongs to exactly one chunk; display-only repeated
  // context does not count as duplicated review coverage.
  if (fileParts.join("\n") !== whole.patch ||
      chunks.length !== compare.files.reduce((sum,_,i) => sum +
        chunks.filter(c => c.fileIndex === i).length, 0)) {
    throw Error("review_chunk_coverage_mismatch");
  }
  return { ...whole, chunks };
}

// Narrow deterministic backstop. Scan *added* executable lines only; deleted
// lines, diff headers, comments, and examples in strings are not findings.
// This intentionally catches only direct credential-header logging, not all
// possible data leaks. A model's NO_FINDINGS cannot override this signal.
export function hasAddedCredentialLogging(patch) {
  if (typeof patch !== "string" || Buffer.byteLength(patch, "utf8") > MAX_PATCH_BYTES) return false;
  const directLog = /^(?:console|logger|log)\.(?:log|debug|info|warn|error)\s*\(\s*(?:req|request)(?:\?\.|\.)headers(?:(?:\?\.|\.)(?:authorization|cookie)\b|\[\s*['"](?:authorization|cookie)['"]\s*\])/i;
  return patch.split("\n").some(line =>
    line.startsWith("+") && !line.startsWith("+++") &&
    directLog.test(line.slice(1).trimStart()));
}

export function consolidateChunkReviews(reports, scope, chunks) {
  if (!Array.isArray(reports) || !Array.isArray(chunks) ||
    !chunks.length || chunks.length > MAX_CHUNKS || reports.length !== chunks.length) {
    return makeBlockedReview(scope, "incomplete_model_review");
  }
  let sawInconclusive = false;
  let sawChanges = false;
  const findings = [];
  for (let i = 0; i < chunks.length; i++) {
    const report = reports[i];
    const chunk = chunks[i];
    if (!report || report.reviewer !== "AI-09" || report.evidenceClass !== "AI_ASSERTED" ||
      report.githubApprovalSatisfied !== false || report.mergeAuthorized !== false ||
      report.independentGitHubAccountVerified !== false || report.physicalEvidenceVerified !== false ||
      !["NO_ACTIONABLE_FINDINGS", "CHANGES_REQUESTED", "INCONCLUSIVE"].includes(report.status) ||
      report.scope?.headSha !== scope.headSha || report.scope?.baseSha !== scope.baseSha ||
      report.scope?.patchSha256 !== createHash("sha256").update(chunk.patch).digest("hex") ||
      JSON.stringify(report.scope.paths) !== JSON.stringify(chunk.paths) ||
      !Array.isArray(report.findings) ||
      report.findings.some(finding => !chunk.paths.includes(finding.path))) {
      return makeBlockedReview(scope, "review_chunk_invalid_or_blocked");
    }
    if (report.status === "INCONCLUSIVE") sawInconclusive = true;
    if (report.status === "CHANGES_REQUESTED") sawChanges = true;
    findings.push(...report.findings);
    if (findings.length > 20) return makeBlockedReview(scope, "too_many_review_findings");
  }
  const status = sawInconclusive ? "INCONCLUSIVE" :
    sawChanges ? "CHANGES_REQUESTED" : "NO_ACTIONABLE_FINDINGS";
  // The backstop does not invent AI findings or authorize a fix.
  // If a model incorrectly declares a known dangerous addition clean, HOLD.
  if (status === "NO_ACTIONABLE_FINDINGS" &&
    hasAddedCredentialLogging(chunks.map(chunk => chunk.patch).join("\n"))) {
    return makeBlockedReview(scope, "deterministic_sensitive_logging_risk");
  }
  return {
    version: 1, reviewer: "AI-09", scope,
    status, findings, blockers: status === "NO_ACTIONABLE_FINDINGS" ? [] :
      [status === "INCONCLUSIVE" ? "review_chunk_inconclusive" : "model_findings_require_action"],
    evidenceClass: "AI_ASSERTED", githubApprovalSatisfied: false,
    independentGitHubAccountVerified: false, physicalEvidenceVerified: false,
    mergeAuthorized: false,
  };
}

export function makeBlockedReview(scope, reason) {
  return {
    version: 1, reviewer: "AI-09", scope,
    status: "BLOCKED", findings: [], blockers: [reason], evidenceClass: "AI_ASSERTED",
    githubApprovalSatisfied: false, independentGitHubAccountVerified: false,
    physicalEvidenceVerified: false, mergeAuthorized: false,
  };
}

export function reviewReceipt({ repository, prNumber, headSha, baseSha, trustedSha, ciRunId, ciConclusion, result }) {
  return { schemaVersion: 1, repository, prNumber, headSha, baseSha, trustedSha,
    ciRunId, ciConclusion, reviewerResult: result };
}

function hasControl(value) {
  return [...value].some(char => char.charCodeAt(0) < 32 && ![9, 10, 13].includes(char.charCodeAt(0)));
}

function hasPotentialSecret(value) {
  // Untrusted model output must not be published when it resembles a credential.
  // False positives safely block a comment rather than leaking private material.
  return /(?:gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,}|sk-proj-[A-Za-z0-9_-]{12,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|(?:authorization|api[_ -]?key|secret|password|access[_ -]?token)\s*[:=]\s*[^\s,;]{8,})/i.test(value);
}

export function validateReviewReceipt(receipt, expected) {
  if (!receipt || typeof receipt !== "object" || Array.isArray(receipt) ||
    receipt.schemaVersion !== 1 || receipt.repository !== expected.repository ||
    receipt.prNumber !== expected.prNumber || receipt.headSha !== expected.headSha ||
    receipt.baseSha !== expected.baseSha || receipt.trustedSha !== expected.trustedSha ||
    receipt.ciRunId !== expected.ciRunId || !SHA40.test(receipt.headSha ?? "") ||
    !SHA40.test(receipt.baseSha ?? "") || !SHA40.test(receipt.trustedSha ?? "") ||
    !["success", "failure", "cancelled", "timed_out", "neutral", "skipped", "action_required"].includes(receipt.ciConclusion)) return false;
  const review = receipt.reviewerResult;
  if (!review || typeof review !== "object" ||
    review.version !== 1 || review.reviewer !== "AI-09" ||
    review.scope?.headSha !== receipt.headSha || review.scope?.baseSha !== receipt.baseSha ||
    review.evidenceClass !== "AI_ASSERTED" ||
    review.githubApprovalSatisfied !== false ||
    review.independentGitHubAccountVerified !== false ||
    review.physicalEvidenceVerified !== false || review.mergeAuthorized !== false ||
    !ALLOWED.has(review.status) || !Array.isArray(review.findings) ||
    !Array.isArray(review.blockers) || review.findings.length > 20 ||
    review.blockers.length > 20) return false;
  if (review.status === "NO_ACTIONABLE_FINDINGS" && (review.findings.length || review.blockers.length)) return false;
  if (review.status === "CHANGES_REQUESTED" && review.findings.length === 0) return false;
  if (review.status === "BLOCKED" && review.blockers.length === 0) return false;
  if (review.scope.patchSha256 !== undefined && !SHA256.test(review.scope.patchSha256)) return false;
  if (review.scope.patchSha256 === undefined && review.status !== "BLOCKED") return false;
  const paths = review.scope.paths;
  if (!Array.isArray(paths) || paths.length > MAX_FILES || paths.some(p => typeof p !== "string" || p.length > 250 || !p.trim() || hasControl(p))) return false;
  if (review.findings.some(f => !f || !paths.includes(f.path) ||
    !["low", "medium", "high", "critical"].includes(f.severity) ||
    (f.line !== null && f.line !== undefined && (!Number.isSafeInteger(f.line) || f.line <= 0 || f.line > 500000)) ||
    ["summary", "evidence", "proposedFix"].some(k => typeof f[k] !== "string" || !f[k].trim() || f[k].length > 800 || hasControl(f[k]) || hasPotentialSecret(f[k])))) return false;
  // BLOCKED receipts can intentionally omit the patch digest and path list.
  // Never print arbitrary self-hosted artifact text under that exception.
  // Only locally generated, fixed diagnostic codes may reach hosted comments.
  const blockerCodes = new Set([
    "invalid_scope_or_self_review", "sensitive_paths_require_human_review",
    "local_model_unavailable_or_invalid_response", "model_inconclusive",
    "model_findings_require_action", "review_chunk_inconclusive",
    "incomplete_model_review", "review_chunk_invalid_or_blocked",
    "too_many_review_findings", "review_prerequisite_or_model_unavailable",
    "deterministic_sensitive_logging_risk",
  ]);
  if (review.blockers.some(b => typeof b !== "string" || !blockerCodes.has(b))) return false;
  if (review.status === "CHANGES_REQUESTED" &&
    (review.blockers.length !== 1 || review.blockers[0] !== "model_findings_require_action")) return false;
  if (review.status === "INCONCLUSIVE" &&
    (review.blockers.length !== 1 ||
      !["model_inconclusive", "review_chunk_inconclusive"].includes(review.blockers[0]))) return false;
  if (review.status === "BLOCKED" &&
    (review.blockers.length !== 1 || ![
      "invalid_scope_or_self_review", "sensitive_paths_require_human_review",
      "local_model_unavailable_or_invalid_response", "incomplete_model_review",
      "review_chunk_invalid_or_blocked", "too_many_review_findings",
      "review_prerequisite_or_model_unavailable", "deterministic_sensitive_logging_risk",
    ].includes(review.blockers[0]))) return false;
  return true;
}

export function commentMarker(prNumber, headSha, baseSha) {
  if (!Number.isSafeInteger(prNumber) || prNumber < 1 ||
      !SHA40.test(headSha) || !SHA40.test(baseSha) || headSha === baseSha) {
    throw new Error("invalid_review_marker");
  }
  // A base change invalidates the old review even if PR head is unchanged.
  return "<!-- GORIQ_AI09_ADVISORY_V2 PR=" + prNumber +
    " HEAD=" + headSha + " BASE=" + baseSha + " -->";
}

function safeLine(value) {
  return String(value).replace(/[\r\n\t]/g, " ").replace(/@/g, "@\u200b")
    .replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/\u0060/g, "\\\u0060").replace(/([*_|])/g, "\\$1").replaceAll("[", "\\[").replaceAll("]", "\\]")
    .replace(/(gh[pousr]_[A-Za-z0-9_]{12,}|sk-proj-[A-Za-z0-9_-]{12,}|AKIA[A-Z0-9]{16})/gi, "[REDACTED]")
    .slice(0, 1300);
}

export function formatReviewComment(receipt) {
  const r = receipt.reviewerResult;
  const quote = String.fromCharCode(96);
  const lines = [
    commentMarker(receipt.prNumber, receipt.headSha, receipt.baseSha),
    "## AI-09 Reviewer — automatic local advisory review",
    "**Status:** " + safeLine(r.status),
    "**Reviewed PR head:** " + quote + receipt.headSha + quote,
    "**Base:** " + quote + receipt.baseSha + quote,
    "**Trusted reviewer source:** " + quote + receipt.trustedSha + quote,
    "**CI run:** " + quote + receipt.ciRunId + quote + " (" + safeLine(receipt.ciConclusion) + ")",
    "**Patch SHA-256:** " + quote + (r.scope.patchSha256 ?? "UNAVAILABLE") + quote,
    "**Evidence class:** AI_ASSERTED (local-model advisory, not independent GitHub APPROVED)",
    "**Authority:** No merge, no deployment, no ACL/process changes; existing Human Gates remain.",
  ];
  if (r.findings.length) {
    lines.push("", "### Findings");
    for (const f of r.findings) {
      lines.push("- **" + safeLine(f.severity) + "** " + quote + safeLine(f.path) + ":" + (f.line ?? "?") + quote + ": " + safeLine(f.summary));
      lines.push("  - Evidence: " + safeLine(f.evidence));
      lines.push("  - Proposed fix: " + safeLine(f.proposedFix));
    }
  }
  if (r.blockers.length) lines.push("", "**Review blockers:** " + r.blockers.map(safeLine).join(", "));
  if (r.status === "CHANGES_REQUESTED") {
    lines.push("", "### Findings triage (unverified AI-09 advisory)",
      "REVIEW_ID: ai09:pr:" + receipt.prNumber + ":" + receipt.headSha,
      "SOURCE_AGENT: AI-09 Reviewer",
      "TARGET_STAGE: IndependentTechnicalTriage",
      "STATUS: TRIAGE_REQUIRED",
      "REVIEWED_PATHS: " + r.scope.paths.map(safeLine).join(", "),
      "NEXT_ACTION: Verify the alleged defect on the pinned head with concrete code and reproducible evidence. Only separately confirmed findings may become scoped Builder/Debugger repair tasks. Re-run CI and AI-09 on every changed head.",
      "This advisory does not create, authorize, or acknowledge a Builder/Debugger repair task.");
  }
  if (r.status === "BLOCKED" || r.status === "INCONCLUSIVE") {
    lines.push("", "NEXT_ACTION: Restore trusted local model / evidence, then re-run on an unchanged PR head; treat as HOLD.");
  }
  lines.push("", "**GitHub approval satisfied: NO** · **Independent account verified: NO** · **Merge authorized: NO**");
  const body = lines.join("\n");
  if (body.length > 48000) throw new Error("review_comment_too_large");
  return body;
}
