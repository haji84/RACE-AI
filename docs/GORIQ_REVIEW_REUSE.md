# GORIQ AI-09 reuse

Owner request: reuse the existing GORIQ reviewer for RACE-AI. Local implementation only; no new review engine, paid model API, model download/start, active workflow, repository setting, comment/approval, merge or cloud deployment was performed.

## Existing implementation reused unchanged

Source: [haji84/AI- at accf8294](https://github.com/haji84/AI-/tree/accf8294ff936b73b93e21667d92bc1b52aa8428). The four modules in `vendor/goriq-ai09/` are exact source copies, not rewritten variants:

| Module | Responsibility |
|---|---|
| `ai09-local-reviewer.mjs` | Isolated injected local inference, untrusted diff, structured findings, advisory authority |
| `ai09-pr-review-automation.mjs` | Complete chunk coverage, limits, consolidation, credential-log backstop, receipt validation |
| `goriq-ai09-compare-coverage.mjs` | Compare authoritative addition/deletion counts with full returned hunks |
| `goriq-ai09-finding-anchors.mjs` | Require findings to quote an actual added code line; otherwise HOLD |

`UPSTREAM.json` records source commit, Git blob, bytes and SHA256. The RACE loader pins the manifest digest, verifies all four modules before loading any of them, and loads the verified byte snapshots. `.gitattributes` preserves their source bytes across OS checkouts. Updates require an explicit new pin and review, never `main`/latest at runtime. This is owner-requested reuse between repositories under the same owner; no new license grant is inferred.

The small RACE adapter handles the current workflow's names rather than relabeling its CI as GORIQ's legacy `CI`/`pilot` checks. It requires open same-repository PR/main, exact base/head, linked successful `Four sport synthetic E2E` run, matching GitHub Actions check suite and both OS plus `unit`. It rechecks those facts after inference, including attempt/check IDs. Missing pages, missing files, truncated hunks or changed revisions stop review. Only fixed GitHub GET paths and loopback Ollama are supported. It never executes PR code or calls write endpoints.

## Local commands

From the isolated integration checkout, Node 22+ (tested locally with 24.19.0):

```powershell
node --test tests/goriq_reuse.test.mjs
node scripts/race-goriq-review.mjs --preflight examples/ai09-pr69-request.json
```

The example pins PR69's existing head/base/run. It deliberately becomes stale and refuses if either changes. Preflight reads public GitHub evidence only and never invokes a model. There is no dependency installation. Unit tests inject fixture inference into the real GORIQ core; a passing test is not an AI-09 model review.

Only after a focused PR passes preflight and an already approved loopback model is available:

```powershell
node scripts/race-goriq-review.mjs --review path/to/exact-request.json
```

The command does not install or start Ollama and has no remote/paid fallback. Keep `GITHUB_TOKEN` absent for public unauthenticated reads or use only the approved repository-scoped read-only runner token; never pass a token into the model. Invalid/secret-like output is not published. Non-clean review exits 2. Output always retains `AI_ASSERTED`, `githubApprovalSatisfied:false`, `independentGitHubAccountVerified:false`, `physicalEvidenceVerified:false`, `mergeAuthorized:false`.

## Actual PR69 readiness result — 2026-10-21

The first live preflight made four read-only GitHub GETs and held with `unverifiable_patch_statistics`. One diagnostic compare GET identified `tests/__init__.py`: GitHub reports an added empty file, blob `e69de29bb2d1d6434b8b29ae775ad8c2e48c5391`, zero additions/deletions, and no textual patch. GORIQ's current contract requires a verifiable hunk for every changed file. The 17-file diff has 73,217 returned patch bytes.

A separate **offline diagnostic only** represented the empty file with a no-op hunk in a RAM copy. This exposed a second HOLD, `review_chunk_budget_exhausted`. Neither transformation nor an increased budget is part of the adapter. No file is silently dropped, fabricated hunk admitted or partial review called clean. The original comparison and diagnostic are retained under ignored `artifacts/` for review.

Therefore this patch verifies reuse and safety integration; it does **not** assert PR69 is admitted, queued, reviewed by a real AI-09 model, approved or merged. Making this whole PR eligible needs a separately reviewed upstream policy for empty-file metadata and review batching, or smaller review scopes with separately verified complete coverage. Do not repeat the same held preflight without a concrete change.

## Hosted candidate remains inactive

`docs/workflow-templates/race-goriq-readonly.yml.template` is outside `.github/workflows`. It is a manual, public-repository, owner-only candidate using GORIQ's pinned Ollama binary and loopback model pattern. The copied engine/adapter runs from a separately reviewed trusted source ref, never the PR head. Its preflight precedes any binary/model download. It has read-only permissions, one concurrent run, a 70-minute hard job limit, no artifacts, writes, scheduled triggers or paid endpoint.

Do not activate by renaming it alone. Activation requires the existing owner/safety/cost gate, a reviewed trusted source SHA in `RACE_AI09_TRUSTED_REF`, deliberate `RACE_AI09_READONLY_ENABLED=true`, and verification that standard hosted usage is covered by the applicable free entitlement. The template is not a billing dashboard, free-plan proof or a tested hosted model run. Its model tag follows existing GORIQ; model digest/runtime still need recording during an admitted real run. The original paused automation remains paused.

This advisory cannot replace formal independent GitHub approval/Human Gates. Main remains unchanged. Four-sport real-data E2E and the 98% Hit@8 goal remain unverified; no new real race, prediction POST, held33 retry, Vercel request or source-media retrieval is involved.
