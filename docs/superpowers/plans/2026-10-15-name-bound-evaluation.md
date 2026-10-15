# Name-bound evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax.

**Goal:** Read-only scoring of three frozen forecast phases against independently stored official post-race labels.
**Architecture:** Reuse existing immutable forecast and official result contracts; new pure report/read API, selected-forecast UI, bounded read-only verifier. No new result writer or ingestion relaxation.
**Tech Stack:** Python3.12/unittest, vanilla JS/Node tests, private Vercel Blob and same protected GitHub OIDC workflow.
**Spec:** docs/superpowers/specs/2026-10-15-name-bound-evaluation.md

## Global Constraints

- Same JST date; original forecast/result/name proof/B/v1 untouched; labels postclose only. UNVALIDATED/skip/[] always. Phased inputs are NOT equal information cutoffs or proven physical exhibition phases.
- Full forecast validates with own immutable parents. Selected baseline is its baseline_link.model_id; exactly3 evaluated rows,120 outcomes each,N=1. No prediction generation/adoption/financial claims.
- Existing official result ingestion still rejects unsupported B abbreviations; no prefix relaxation, missing labels do not score. First live result target4R all6 canonical names match.
- Max256000 per normalized object, verifier180s/fourAPIreads/zeroPOST/zeroofficialGET, exclusive files and truthful forensic failure.
- No source during implementation/tests. No Production/main/secrets/trust/permissions/concurrency changes; push probe-only and both source-smoke definitions manual-only before every root push.
- One implementer at a time; only assigned files staged, root owns ops/evidence. Source4R numerical/racelist and3R racelist already complete, never reGET. Operational7R ownproof and new numeric capture are root work on existing pinned app.

## Review Focus

1. Own forecast version versus unrelated latest and changed B/name proof; pin every report to explicit forecast nonce.
2. Result source/capture/cloud clock afterclose and same day, microseconds/midnight; no outcome in predictor inputs.
3. Pending/refund/tie/cancelled/malformed labels and financial-versus-finish independence; empty states never fabricated losses.
4. Full numerical3score replay and correct phased-input comparison scope, no N=1 adoption.
5. Caller failure after final IO or invalid residual inventory, real transport bounds and async race/day/envelope stale UI suppression.

### Task 1: Pure three-phase evaluation and read-only API

**Files:** Create web/name_bound_evaluation.py, web/api/name-bound-evaluation.py, tests/test_name_bound_evaluation.py, tests/test_name_bound_evaluation_api.py. Do not modify legacy evaluation/result/forecast contracts.
**Consumes:** validate_name_bound_envelope, name_bound_inputs._context, evaluation_contract._scores/_result_proof, race_contract.validate_cloud_bundle, api.name_bound_exhibition_store.read_name_bound_exhibition, api.race_store.read_current_race.
**Produces:** build_name_bound_evaluation(forecast,race_bundle,race,now), strict report schema and endpoint from spec. Test fixture helper may live in tests/test_name_bound_evaluation.py, returning race/forecast/result_bundle/actual_afterclose clock for Tasks2/3. Keep helpers semantic valid; use existing synthetic forecast fixture/builders and existing result parser fixtures, never live raw source.

- [ ] Add failing tests: ordinary3scores independently computed plus uniform119/120/log120, exact schema/types/clocks/proofs, old arguments unchanged, malformed otherlatest data never used, pending/missing/nonsettled/refund exclusion, unconfirmed financial but confirmed normal finish scores, wrong names/registration/program hash/preclose result/midnight/tampered forecast reject.
- [ ] Run focused RED; implement pure contract exact spec values and fresh-clock GET-only API.
- [ ] API tests assert exactquery max2, exactforecast nonce, detached projected context, read-only fake client forbidsputs, missingforecast404, proof422/store503, clientclosed and postread/midnight clock handling.
- [ ] Run focused GREEN and fullPython once; inspect diff/self-review; commit only4 assigned files. Return concise status/commit/counts and report file. No source/network.

### Task 2: Explicit selected-forecast result comparison UI

**Files:** Create web/name-bound-evaluation.js, tests/ui_name_bound_evaluation.test.js, tests/ui_name_bound_evaluation_browser.cjs; modify web/app.js, web/index.html, web/style.css. Minimally add new asset basename to existing browser harness static allowlists (same scope as previous name-bound asset), .github/workflows/tests.yml Node checks/test list. No legacy validator edits.
**Consumes:** Task1 frozen report exact schema, current RaceNameBoundExhibition.validateNameBoundComparison and Settlement.programDigest-validated nbEnvelope.
**Produces:** validateNameBoundEvaluation(report,forecast,race,now=Date.now()), renderNameBoundEvaluation(report,forecast,race,now=Date.now()); UMD window RaceNameBoundEvaluation. App explicit GET name-bound-evaluation with exact selected forecast nonce. Clear/abort eval state when clearNameBound/reset/day/race/newversion; keep valid numeric comparison on eval failures. No purchase/ledger/source changes.

- [ ] Write grouped meaningful RED tests for valid3scores, missing/pending/unsupported empty states, exact links/schema/types/clocks/microseconds/changedtruth/tamperedscore/phase scope/UNVALIDATED, escaped text. Compose small synthetic result/report fixture with existing numeric fixture rather than duplicating its large payload.
- [ ] Implement pure JS validator/replay and phase-score renderer as specified. Numerical replay over all120 triples, tolerance1e-12; clock/proof/target checks and no float-hash claim.
- [ ] Add explicit button only for saved numeric envelope. Stale A→B→A/day/version response and timeout/error leave numeric table intact; read-only table horizontal access and labels.
- [ ] Offline browser test can be authored but don't run browser through non-CUA tools in this session. Root will use CUA for actual UI. Static browser allowlists changed only for new asset. Run focused/fullJS + node --check; no repeated fullPython for UI-only unless new concern; latestCI runs all. Commit assigned files and concise report.

### Task 3: Bounded read-only verification caller and same manual workflow

**Files:** Create scripts/verify_name_bound_evaluation.py, tests/test_name_bound_evaluation_caller.py; modify .github/workflows/boat-blob-e2e.yml only new manualmode/input/steps (root later pins app). No trust/subject/env/ref/concurrency/permissions changes.
**Consumes:** Task1 report/pure fixture, existing workflow_session/get_json and source/evaluation endpoints. Exact4GET order today→pinned forecast→race→report; fresh actual now/report as_of replay. New query IDs explicit validated, no olddefault fallback.
**Produces:** run(race_id,forecast_request_id,output_dir,execute=False) returning exact manifest; verify_response and verify_backups pure helpers for root restore audit. Five normalized files and strict failure rules from spec.

- [ ] RED tests dryrun no IO, exact4API/0POST/0source positive replay, commit/race/nonce/targets, oversized/truncated/malformed reports/parents, monotonic180 budget, no retries, exclusive paths, fullreadbacks and residual inventory; delayed manifest/finalverification cannot retainCOMPLETED.
- [ ] Implement minimal caller and exact workflow mode/input/quoted env; upload5allowlistedfiles/14days, restore/wholebytes/strictmanifestcoverage. Expose safe counters/codes only.
- [ ] Test real workflow Python blocks compile, push/manual guards, identity/permissions/concurrency unchanged, caller budget RuntimeError propagation. Focused GREEN + fullPython once after backendcaller change. Commit assigned3files, report exact SHA/counts.

## Root execution gates after tasks

- [ ] Independent task reviews and most-capable final increment review; no repeated completed prior plan. Root original branch a2aeec8 clean, next own SDD workspace only.
- [ ] New4R result once on existing approved job: validate currentJST/closed/absent result, all5writer states/lease; independently restore normalized result archive and full API. No new forecast generation/source4numeric reacquisition.
- [ ] Root keeptime: new7R proof already dispatched once17:05; restore/API audit it, capture numeric7 only when exhibition available near17:52 and before18:04 with>180s start. Daily source refresh only after17:31:38 (>6h), once and serialized, if no other real refresh happened.
- [ ] Freshbothmanualsmokegates, push/reviewed WindowsLinuxCI/READY, exact pin updates only afterno activewriter; same protectedOIDC sourceapp version.
- [ ] One manual name-bound-evaluation verification for completed4R forecast38699263834-1; full5files/4API report replay/independent120-term metrics, no source writes in verifier. Root capture actual PC1440/mobile390 and reject stale UI result context.
- [ ] Old frozen4R/3proof/v1/baselines maintained; current day may change only authorized6hrefresh with clocks/evidence. Commit evidence/state/PR, exact evidence-successor CI/READY/API, update existing quiet hourly automation. Project remainsincomplete; newlabelaliasingest and multiday/video proof remain nextwork.
