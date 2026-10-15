# Official result and local ledger settlement

**Goal:** Connect verified cloud result evidence to existing manual purchase records and shared integer-yen accounting, without creating purchases or trusting restored financial claims.

**Authority:** Owner instruction to complete RACE AI, handover chapters 15–16, 36–37, 48, 52.3–52.4 and 53.10; existing `docs/MONEY_ENGINE.md` and `docs/OPERATIONS_STATE.json`. Ordinary design, implementation, tests and protected Preview are authorized autonomously. Production, betting, payments and trust expansion remain excluded.

**Design:** A read-only current-day `/api/settlement?race_id=...` reads the approved stored program and immutable race receipts, checks their complete canonical/time/identity chain and exports only positively verified market results. Browser accounting derives a temporary settled projection of existing local manual records through `RaceMoney.settle_bets`/`summarize_ledger`. The original purchase ledger remains unchanged. Persisted result audit entries retain distinct snapshots and correction history but never establish current financial confirmation after reload; a fresh protected same-origin API response is required.

**Tech stack:** Existing Python stdlib contracts/Vercel private Blob, dependency-free browser JavaScript, Node tests and real browser regression. No new dependencies or credentials.

## Constraints and interfaces

- All API timestamps are actual timezone-aware clocks; current JST day only in this increment. Historical records remain pending until historical result reading is implemented.
- No original source requests, official-page parsing, forecast regeneration, ledger upload, wager or payment in the settlement API/UI.
- Verified per-market coverage can settle that market even when another market is missing. Missing purchased markets leave that purchase pending. Returned-boat rules, unverified ties, postponement without explicit full refund and missing refund evidence are excluded.
- Explicit positively confirmed full-race refund can settle through existing Money refund statuses. Special payout only uses the explicit per-100 amount. No inferred losing tickets from incomplete coverage.
- Corrupt stored data returns 422; storage failures 503; strict single `race_id` query; no-store/nosniff/noindex; close SDK clients. Missing/pending results return informative empty reports.
- API report exact fields: `schema_version:1,race_id,date_jst,as_of,closed_at,program_sha256,status,markets,excluded_market_types,result_proof,exclusion_reason`. `markets` is an array of complete Money-compatible single-market official results: `{race_id,status,confirmed:true,verified_market_types:[bet_type],payouts,refunds,special_payouts}`. No purchase fields. Status: `RESULT_NOT_OBTAINED`, `RESULT_PENDING`, `SETTLEMENT_READY`, `SETTLEMENT_PARTIAL`, `SETTLEMENT_UNSUPPORTED`. `result_proof` matches existing evaluation result proof fields or is null. Seven supported types are the existing Money market names. `exclusion_reason` is null for ready and a fixed bounded reason otherwise.
- Browser validates report identity, clocks, source URL, proof and market shapes; same-origin API is the factual authority. Raw local-storage `official_result` remains ignored. No forged local result may affect ROI.
- Read/modify/write result-audit operations use the existing Web Lock and preserve another tab's updates. API failure clears that race's current derived confirmation. Results panel shows pending/settled/refund amounts and proof, plus an accurate hit count from settled effective records; no fabricated user performance.

## Task 1: Pure settlement report and read-only API

Owner: isolated backend implementer. Files: `web/settlement_contract.py`, `web/api/settlement.py`, narrow shared receipt-check extraction in `web/race_contract.py` and `web/evaluation_contract.py` if needed, `tests/test_settlement_contract.py`, `tests/test_web_settlement_api.py`. Reuse full existing validators, not weak flag checks or duplicated money arithmetic. Export `build_settlement_report(race_bundle, race, now)`.

- [ ] Write and observe failing behavior tests for complete winning/losing markets, partial coverage, pending payout-only, missing result, explicit refund, unsupported return/tie and special payout.
- [ ] Implement minimal pure checked report, preserving input objects and strict proof chain; reject tampered identity/hash/cloud clocks/market coverage and day mismatch.
- [ ] Implement API using stored approved program, current race reader and actual clock; test query/no-store, absent result, close-on-error, 422/503 and midnight handling.
- [ ] Run focused and full Python suite. Return owned diff and verification evidence; root commits integrated change.

## Task 2: Browser accounting, audit and display

Owner: isolated UI implementer. Files: `web/settlement.js`, `web/app.js`, `web/index.html`, narrow `web/style.css`, `tests/ui_settlement.test.js`, `tests/ui_settlement_browser.cjs`. Backend files and existing shared money engine are outside this task.

- [ ] Write and observe failing pure/browser regressions: 400 yen at official1580 per100 returns6320/net5920; losing record; pending missing market; local forged result ignored; same snapshot idempotent; correction appends proof; stale response/race/day and API failure cannot retain confirmation; two-tab audit update preserves both.
- [ ] Implement `RaceSettlement` response validation and ledger projection using `RaceMoney` functions. Purchase ledger is never changed by settlement; audit is not financial authority after reload.
- [ ] Automatically fetch bounded same-origin reports for relevant current-day recorded races; integrate safe reload/storage/abort behavior and accurate financial history/status display. Show all-history versus today totals honestly.
- [ ] Run all JS tests and six browser regressions; full Python suite at integration boundary. No live user records or hypothetical real purchases are created.

## Task 3: Independent review and real verification

Owner: root plus fresh independent reviewer. Root owns CI configuration, evidence/operations docs and PR metadata.

- [ ] Review changes against spec including partial-market false losses, refunds, special payouts, evidence correction rollback, mutated local storage and cross-tab concurrency; fix confirmed findings with regression tests.
- [ ] Run Python/JS/full browser checks, push functional commit, verify exact-head Windows/Linux CI and protected Preview.
- [ ] Read actual Naruto1R settlement report and independently replay against stored result proof. Demonstrate arithmetic only as a clearly labelled hypothetical calculation; create no actual purchase or ledger record. No additional official source GET needed.
- [ ] Record source proof, empty real ledger, tests, current-day scope and remaining historical/multirace work. Update Draft PR64 and continue the next executable completion requirement.

## Preflight consistency and rulings

| Tasks | Shared boundary | Finding |
|---|---|---|
| 1 / 2 | Exact response fields and Money single-market contract | Defined above; backend owns Python, UI owns browser files; no shared edits |
| 1 / 3 | Canonical result proof and real API replay | Existing live result retained; verification is read-only |
| 2 / 3 | Tests, audit and history display | CI paths owned by root; local audit is never restored as authority |
| 1 | Tests against market/refund contract | Reject unsupported mappings; no claim of all refund cases completed |
| 2 | Ledger versus projection/audit | Original ledger unchanged; fresh API needed after reload |
| 3 | Actual evidence versus synthetic records | Never seed Preview with a fake historical purchase |

Ruling: Implement independent backend and browser files concurrently under handover chapter37; exact interface above prevents edit conflicts. Ordinary approval gates in generic process skills are superseded by the owner's explicit autonomous execution instruction. Cost if interface assumptions are wrong: integration rework, with no user data mutation.

Progress: starting from functional/evidence head87169ab, clean shared completion branch. Latest CI38658335307:499 Python per OS (one optional skip),31 JS; Preview mwrmxx3bl verified. Whole-product completion remains open.

## Parallel next increment: bounded national research cohort

Root owns `scripts/publish_research_cohort.py` and `tests/test_research_cohort_caller.py`, independent of settlement files. Select at most24 upcoming races, one earliest race per active venue, from the same approved current-day feed. Default limit24, caller can lower it; require120-second margin initially and again before each POST. Never create past predictions, rewrite a saved prediction, or collect official source pages. Existing `/api/publish-prediction` remains the only server-generated writer under the same scoped OIDC workflow. A GET of an existing prediction must fully validate its receipt before skipping; malformed existing evidence stops the run. New requests/receipts and a bounded manifest are exclusive normalized files in a new output directory. On partial failure retain completed files for backup; never include credentials. Reuse the single-race caller's readback verifier. A JST day rollover or expired target skips remaining writes, preserving completed evidence. Test selection, no-network dry run, no-overwrite, existing-preservation, exact new readback, time rollover and partial failure. Add an explicit cohort mode to the dedicated workflow only after reviewed code, CI and exact Preview readiness; pin immutable targets, maintain existing concurrency and trust. Back up and byte-restore only the normalized cohort directory. Actual cohort size and later evaluated races remain separate.
