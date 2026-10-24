# AGENTS.md — RACE-AI Codex safe parallel development contract

This file is a **proposal on Draft PR #72**, not an assertion that it is on main. It must not weaken or overwrite the existing Draft PR #61 AGENTS.md without an independent merge review.

## Always read before any implementation

1. docs/CODEX_RACE_AI_THREE_STREAM_MASTER_HANDOFF_20261025.md
2. docs/CODEX_RACE_AI_PARALLEL_RUNBOOK_20261025.md
3. docs/CODEX_RACE_AI_START_PROMPT_20261025.md
4. GitHub Issue #67 (adopted ultimate GOAL), Issue #68 (live implementation orchestration)
5. Current actual main, PR #61/#64/#65/#69/#71/#72 head/base/changed files/check runs. A handoff snapshot is not live state.

## Product and authority

Four sports, all scheduled/sold/evaluable races, odds-independent full-trifecta Top8 per actual model, protected immutable **pre-official-cutoff** freeze, settlement revisions and prospective model-versus-model PDCA. Unforecast races stay in the full denominator. 98% prospective Hit@8_all is **unreached and unproven**, never promise it. No automatic betting.

Presentation sources trigger **on observed official publication**, not an arbitrary T-10 threshold: boat exhibition, autorace trial, keirin rider presentation, horse paddock and separate race-day bodyweight. Available does NOT mean model-ready, original publication timestamp proven, or source license granted. First-party site HTTP200 is not an automated reuse license. No fake F/L, no inferred wind bearing from generic icons, no post-cutoff snapshots or result/odds leakage.

Odds are a separate **post-forecast economic information** feed: existing PR #71 Cloudflare owner-only D1 worker and Safari viewer. Past real 120-trifecta/D1 success is not proof of 60-second three-cycle owner iPhone E2E. T-60 refresh in existing code vs owner-considered T-15/T-10 is explicitly unresolved; do not silently change agreed semantics.

## Parallel development and PR hygiene

Use existing Draft PR #72 for provider/source/event integrity, PR #71 for odds and forecast (both share one branch!), PR #64 for read-only K/B source reuse, PR #69 for baseline E2E; PR #65 is a read-only controller pilot, not a working autonomous loop. DO NOT open redundant PRs, mass-merge stacked drafts, force push, reset another developer's changes, or weaken branch protection. Track atomic writer ownership and exact expected branch HEAD. **B odds and C model lane cannot push concurrently to the PR #71 branch**; they may prepare separate worktrees but one serialized integrator performs writes with CAS/lease. The independent reviewer must not be a builder or CodeRabbit.

Every slice: Define Goal/Done -> inspect existing implementation -> independent design criticism -> implement smallest change -> tests/CI exact HEAD -> independent AI-09 or separately authorized model review -> minimal fixes/retest -> lawful real input or owner Safari acceptance -> only authorized integration -> update Issue #68 -> choose next highest-dependency task. Do not stop at writing plans or synthetic tests. Fail closed if source rights or provenance unknown while continuing other permitted work. Persist interruption/recovery evidence and blocked Owner action. An AI review is not a proper GitHub APPROVED.

## Critical Owner Human Gates

Explicit authorization is REQUIRED for changes to top-level Goal or fundamental design, destructive DB/storage migrations, source-rights expansion, new paid/cloud commitments or shared free-tier impact beyond reviewed caps, Production/public deployment, Access/security/credential changes, formal GitHub review policy/branch protection, unlicensed raw source/video distribution, aggressive continuous scraping, automated wagers/payments. This instruction is not blanket permission.

## Privacy and evidence

This repository is public. Never commit or log owner email/address/account IDs, Cloudflare API tokens, secrets, Access JWT, private source data, unlicensed original HTML/film/images, full odds vendor-origin tables, identifiable personal records, or privileged snapshots. Use SHA/aggregate counts/approved reference IDs. Keep SYNTHETIC_CI_PASS, REAL_SOURCE_OBSERVED, OWNER_IPHONE_PASS, INDEPENDENT_GITHUB_APPROVED, MAIN_INTEGRATED and REAL_PROSPECTIVE_FORECAST evidence distinct. Do not claim unattended operations without actual scheduler/control-loop and recovery runs.

## Safe starting command to the agent

Re-fetch PR heads and Issue #67/#68, create or refresh the taskboard/evidence matrix described in the runbook, obtain lane-specific writer locks, begin rights/as-of/odds firewall and the shortest prospective end-to-end validation that does not cross an unresolved Human Gate. When genuinely blocked, state the exact one owner action and preserve the current HEAD, CI and restart pointer in Issue #68.
