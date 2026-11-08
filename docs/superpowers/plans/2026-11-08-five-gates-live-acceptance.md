# Five Gates Live Acceptance Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans within each ownership domain and superpowers:dispatching-parallel-agents for independent domains.

**Goal:** verify the requested forecast, settlement, input, retention and PDCA paths with authenticated real data.
**Architecture:** reuse the existing source-free retained-audit Actions job and encrypted Git state. Keep the separately owned native source transaction fixed; append count-only verification rather than replacing model or financial logic.
**Tech Stack:** Python/unittest, Node, Playwright, existing AES-GCM/Git transport.
**Spec:** `docs/superpowers/specs/2026-11-07-boat-five-completion-design.md`, as renewed by the user's five-item request on 2026-11-08.

## Global Constraints

- GitHub only; no new task, workflow, job, schedule, permissions, provider, charge or bet.
- No shared native-branch push during the reviewed first-CI/issuer/source transaction.
- Keys and real private state stay in existing Actions; no local operator-file access.
- Preserve forecast clocks, originals, outcome journals, frozen allocation and retired-model history.
- Seller revival awaits the user's clarification; other work continues independently.

## Review Focus

- Budget inputs can change while displayed financial totals stay stale: compare actual figures for both budgets.
- Refunds and pending purchases must remain distinct from zero-valued losses.
- An unknown model's cutoff or input metric must remain unknown rather than be inferred.
- A restored Git snapshot must work without a live/expired artifact fetch or local file dependency.
- Historical descriptive gains must not become prospective improvement or promotion claims.

## Task 1: Numeric owner-site acceptance

Files: `scripts/boat_saved_site_context.py`, `scripts/boat_saved_site_check.cjs`, their existing tests, and a narrow Node helper if needed.
Consumes: authenticated selected-day feed and unchanged saved-performance calculation.
Produces: private bounded aggregate expectations and actual browser comparisons for day budgets 10000/5000 and race budgets 800/1000.

- [x] Reproduce the gap: the old checker verifies labels/input values, not financial equality.
- [x] Add failing stale-budget, wrong payout/refund/pending, and wrong-group cases.
- [x] Implement numeric matching without changing financial calculation or exposing picks.
- [x] Verify local tests, independent review and actual three-width Actions browser.

## Task 2: Saved-data PDCA without a fitted-runtime dependency

Files: `scripts/boat_prospective_audit.py`, `scripts/saved_performance_report.cjs`, new `tests/test_saved_comparison_audit.py`.
Interface: `--saved-comparison-day YYYY-MM-DD --daily-budgets 10000,5000 --output <private path>` reads only authenticated selected-day saved data. Existing prospective-plan mode remains unchanged. Node CLI accepts the same optional daily-budget list; `report(view, options)` stays unchanged.

- [x] Test absent runtime/frozen plan, genuine Node aggregates, budgets, zero source access, privacy and no mutation; observe RED.
- [x] Implement the explicit descriptive mode, preserving false improvement/receipt/promotion flags.
- [x] Run new and existing Python/Node suites; obtain independent review.
- [x] Run once in the existing guarded audit job and retain safe real-data counts.

## Task 3: Retention and environment-independent continuation

Files: existing vault/maintenance/control readers; a new narrow read-only verifier only if an actual acceptance gap is found.
Consumes: verified closed-worker metadata and encrypted retained ZIP/metadata/raw-source/control entries.
Produces: count-only independent-restore evidence or precise missing immutable references.

- [x] Separate prior implementation tests from actual last-worker retention evidence.
- [x] Select a Git-only independent restore path; no backfill writer or worker startup in a read-only proof.
- [x] Verify fresh-runner bytes, source control/counter conservation and no live artifact fallback.
- [ ] Record continuation through the existing hourly coordinator and current native owner.

## Task 4: Remaining data and real forecast/PDCA acceptance

Files: existing source/evaluation operator plans and count-only evidence.

- [ ] Resolve seller scope from the pending user answer; never substitute fractions for rating points.
- [ ] Observe the canonical owner's remaining AUTO/KEIRIN data, actual model fits and restored model count.
- [ ] Integrate reviewed forecast-only publication at the owner's permitted boundary, after original retention/proof and before result work.
- [ ] Require current-day pre-cutoff originals and site visibility; retain later official result and matched comparison evidence.
- [ ] Report each gate from actual evidence; a valid PDCA conclusion may be no demonstrated improvement.

## Execution Ledger

- Baseline: isolated worktree at public `8a6c05e60af492b68b0c44e044dd15df750199dd`; shared native `7aa7ad24` has whole first CI success and is owned by the other active controller.
- Pre-flight: Tasks 1/2 share authenticated-view semantics but own disjoint files; Task 3 is read-only until its gap is established. Root alone owns workflow integration.
- Ruling: keep original prospective-plan mode intact and add an explicit descriptive mode; absence of a local fitted-runtime marker must not prevent an authenticated saved-data comparison.
- Ruling: user execution is already authorized; the only open question is seller scope, not permission to continue the other gates.
- Task 2 implementation verified: 16 Python tests and 29 Node tests passed; an independent review reran 16 Python and 6 report tests with no blocker. Literal 1R1000 cases preserve payout2400/refund1000/pending1000 while a 5000 daily budget buys5 races and a 10000 budget buys8. Real-data Actions execution remains pending.
- Task 3 review finding: authenticated GitHub metadata captures are not evidence of retained official result-source captures. Require the terminal worker's raw-capture inventory before claiming complete raw restoration.
- Task 3 implementation verified: 71 scoped retention/recovery/mirror tests passed; independent and root runs each passed the 16 new cases. Full status requires the terminal 7f locator and 11 unique official result receipts. Generic restoration remains explicitly partial. Actual fresh GitHub-runner proof is pending.
- Ruling: live acceptance uses the existing BOAT display job because it already has `contents:write` and `actions:read`; the daily result job does not have the artifact-read permission needed for closure maintenance. Reuse the isolated display branch and guard; do not increase permission scope. Keep the job's 20-minute limit and the source job's 360-minute limit.
- Task 1 implementation verified: explicit key-free Node child, bounded input, aggregate-only private context, exact group/day/generation and four-scenario DOM checks. Independent review is clear. Root combined verification passed 63 Python and 54 Node tests, including actual browser DOM with zero skips. Actual deployed-site numeric verification remains pending.
- Actual Tasks 1/2: run 42441153938 verified the Nov7 generation78 owner site at 320/390/1440, including 12 exact numeric budget cases (10000/5000 daily and 800/1000 per race), with the cap exercised. Saved comparison read 1559 forecasts in 64 model/stage/variant/version groups. Six matched weight-version comparisons had zero hit difference; no improvement was demonstrated. This run remained failed because independent retention verification held. Count-only evidence: `docs/evidence/2026-11-08/five-gate-numeric-pdca-actual-counts.json`.
- Actual Task 3 diagnostic: retention-only run 42442895611 restored all 39 selected originals and 8 source-capture bundles, reading 40330109 bytes, then failed in the official B capture URL validator. Its import of the complete day collector required an absent optional PR72 bridge. Replace only that dependency with the already pinned PR64 archive URL helper; never increase limits, introduce a checkout, or alter source captures. The regression failed before the fix, then new/vault/verifier suites passed 44 tests with zero skips. Fresh-runner acceptance remains pending until the repaired job passes.
- Actual Task 3 restore: repaired run 42443965999/head8f9b37f completed SUCCESS at 03:46:08Z. A fresh bare Git restored 39 originals and 55 capture records from 11 bundles (including the required 11 terminal official result captures), authenticated the closed-run catalogue and control/continuity mirror, and read 41334586 bytes. Live artifact requests, official source requests and upstream writes were zero. `automatic_continuation_proven` remains false: this proves independent restoration, not a completed source-worker handoff. Evidence: `docs/evidence/2026-11-08/retained-run-actual-acceptance-counts.json`.

## Actual-operation follow-up within the approved five-gate scope

Current-day run 42444232865 correctly failed: generation80 had 14 native P1 races, 11 groups and no future native original (last cutoff 1650 seconds old). Closed source 42439206540 finished SUCCESS at 03:49:52Z after five rounds/155 requests and its bounded session end. Its r3 original was saved at 03:02:17Z but published at 03:18:55Z; r4 was saved at 03:19:27Z and published at 03:35:14Z. Preserve the failed acceptance; a historical check cannot replace it.

The source's learning-retention step reported 210 folders and took approximately ten minutes. Public transfer-ref metadata shows repeated learning-subtree commits overlapping the native issuer's failed CAS window. This supports batching that writer, not weakening the issuer's stale-parent rejection; exact commit-to-job attribution remains unproved. The last result publisher also rejected a reason-only conflict with unchanged source bytes. Identical original observations can reproduce that signature through differing derived rejection classifications, so do not discard observations or relax the strict merger.

The implementation choices remain GitHub-only Python/Node, the same encrypted refs, authentication and receipt clocks, the same jobs, and no new source request or worker. These are operational repairs of the existing accepted design.

- [x] Learning retention: add bounded batches of the existing exact encrypted three-file candidates. Authenticate before each batch's Git operation, compare immutable paths, use one commit/push per bounded batch and verify every candidate remotely. Preserve the single-candidate API, old pinned pointers, source-archive route, fail-closed CAS and credential cleanup. Test mixed/new/existing candidates, duplicates/conflicts, corrupt readback, aggregate memory bound and no stale-parent retry.
- [x] Authenticated PC replay: add an explicit `--replay-vault-config` mode to the existing saved-view publisher, bypassing model/runtime generation. Authenticate the exact closed ac3 RESULT original and retained capture bundle. Use actual journal observations for new receipts and exact existing observations for known receipts; raw PC bytes are only projection inputs to the existing result engine. Keep genuine observation conflicts held, all rejection/history records and original forecasts intact. Test encrypted history, idempotence, bad bindings, changed observations and zero source access.
- [x] Live routing: in the existing isolated display job, add an explicitly guarded `saved-view: forecasts-first reconcile-closed` route invoking the configured Nov8 replay and an explicit Nov8 numeric site check. It must not require future forecasts or claim gate1 success. Preserve every existing ordinary, historical five-gate and retention-only condition, timeout and source exclusion. Use the existing prefix/ref/actor/repository checks and final failure gate.
- [ ] Independently review and run the explicit source-free reconciliation. Publish safe counts, retain any actual failure and hand off only minimal reviewed patches at the canonical native owner's allowed boundary. Observe actual future publication and all-model fitting separately.

- Bounded learning batches: encrypted 210-candidate RED produced 210 commits; implementation produces one commit with identical files/counts. 37 focused tests passed, and independent review passed 36 tests, including real local Git, old pointers, byte/count splits, changed snapshots, stale-parent/no retry and credential cleanup. Real-worker latency and capsule issuance remain unproved until the canonical owner adopts it.
- Vault replay: 50 related tests passed before the final child-environment fix; 17 replay/forecast tests then passed with the fix and a real poisoned-parent Node regression. Child processes receive only PATH/LANG/TZ. Existing PR72/model collectors, HTTP, runtime and catchup were explicitly denied in CLI tests. Independent replay review and actual execution are still required.
- New reconciliation routing: 18 focused tests plus independent 18 tests/96 owner-condition cases passed. The default forecast-only recovery run is updated to existing active successor 42444478902 (aa57a929); recovery already accepts authenticated immutable artifacts in active runs. The historical 7f restore and closed ac3 replay targets remain separate. No new official-source worker is started by this change.
- Actual retained PC replay: run 42446549272/publicf97ccff authenticated all 57 journal observations as existing, applied 51 of 53 retained capture records and left two older unmatched captures unapplied. It verified generation86, unchanged originals, exact prior encrypted generation and authenticated readback, with zero source/artifact requests. No row change was needed. The Nov8 context then confirmed47 results, but browser verification failed at 04:25:18 with a generic code. Whole run remains failed; current-day numeric/site acceptance is not claimed. Add only safe stage/field/owned-line diagnostics before identifying and fixing the actual browser failure.
- Minimal native integration handoff: public5bbe6fb/tree7872d78037a65d293c5826e76edcc7a67eecdb83 on the existing isolated native handoff branch contains the preserved forecast-first hook plus only pinned-URL import, bounded learning batching and reader-child environment changes. Independent exact-file/order review is clear and 25 native-focused tests passed. No active worker or shared native branch has adopted the handoff yet; actual future publication, time savings, fitting30 and automatic continuation remain pending.
- Browser diagnostic follow-up: preserve the original generic failure and add only allowlisted phase, field, width, progress, error class/code and a fresh constant-message owned callsite. Never inspect or print thrown messages, stacks, assertion values or private input. Poisoned-error/stack-formatting tests and two stale-marker regressions showed RED then GREEN; 23 checker tests passed with zero skips, including actual DOM recalculation. Independent review passed 21 tests before the final two test-only additions and found no assertion, time, retry or admission changes. Actual failure classification is still pending the next guarded run.
- Actual browser classification: run42448077548/publica36 replayed the same sources successfully at generation87 with50 confirmed results. Browser rejected in `research_audit`, width320, before any numeric scenario; no financial or clock cause was established. The next diagnostic marks each research operation and passively collects at most eight sanitized public-script error locations. Implementer, independent review and root each passed 25 checker tests without skips or acceptance changes. Matching published app/helper assets plus invented current-day/live-context stress fixtures passed at320/390; the actual failure operation still needs the next live diagnostic.
- Current closed-run retention selection is advanced from7f to authenticated closedac3/run42439206540 with its exact53-receipt capture locator. The7f config/proof stays unchanged and active display run42444478902 stays separate. Workflow parameter/locator updates passed19 focused tests; guards, timeouts and source exclusion remain unchanged. Independent ac3 restoration is pending execution.
- Actual ac3 catalogue prerequisite: readonly42449229845 correctly stopped at `CLOSED_RUN_CATALOGUE_REQUIRED` before reading originals. Full run42450205048 then completed bounded catalogue backfill for the three known source runs (two new closed catalogues, pending work0, no new originals/source requests) and authenticated the existing ac3 control mirror. Its historical browser failed during saved-view loading with a passive TypeError, so the later verifier did not run and the whole run remains failed.
- Permanent closure integration is now reviewed in both worktrees: the existing normal-worker handoff step runs bounded default-discovery backfill before its unchanged mirror command. No jobs, source requests, permissions, timeouts or source counters are added. Publication33/native16 implementer tests, native19 root tests and independent exact-YAML review passed. Minimal native handoff is public658da56d306559b1ab91f40e92e83af952be2037/treee54df369882fabc568b7e8009c4b7e0b241e0441. Adoption and a fresh actual restore remain pending.
- Versioned public error locations: the deployed assets use exact digest queries, so diagnostics now permit only an exact known public JS URL with no query or one lowercase hex v parameter of length12..64. Output retains only basename/line, plus fixed error/unhandledrejection kind; both listeners share8 records. Implementer and independent runs each passed27 tests, with no stack/message inspection or acceptance changes. The next current-day browser run is needed to identify the TypeError line.
- Actual research root cause: run42451533738/public42a7 reached returned-rationale validation (marker468) at generation91/results63, then Playwright rejected a CSS locator matching both new public headings: rationale and outlook. Real Chromium reproduced that exact strict-mode violation. Fix only the verifier selector to require one exact accessible rationale heading inside the forecast panel, retaining visible-text equality and every other criterion. Implementer and independent suites passed28 tests with zero skips, including negative missing/duplicate/outside-panel/spoof cases. Actual current numeric acceptance remains pending.
- Closed verification advances to AA57/run42444478902 with its authenticated32-receipt terminal bundle after normal source588/run42450915404 began. Its closed catalogue was sealed by the previous maintenance pass. Active forecast display now selects588 while ac3/53 replay stays separate and old capture proofs remain unchanged. Parameter-only19 tests passed. The normal source588 composite is still the old21f1a05 blob and has not adopted the prepared native operational hook.
- Actual latest-AA restore: run42452256640/job128643788040 completed SUCCESS at05:50:14Z. Fresh bare Git authenticated12 original archives,4 bundles/65 capture records, the required32 terminal receipts, closed catalogue and control/continuity cipher binding. It read19719421 bytes with zero live-artifact/source requests or upstream writes. Automatic continuation remains unproved; restoration is a separate gate.
- Current-day retry42452461333 stopped before the browser with FEED_VAULT_REPLAY_READBACK_MISMATCH at05:55:22Z. Feed commits occurred during its05:52:48–05:55:22 interval, but their writer and exact failed predicate are not established. Preserve this failed attempt and all strict readback/generation checks; do not call it a browser or financial failure. Add a separate guarded verify-current route that performs no replay or write and checks explicitNov8 context and the unchanged numeric browser independently.
- Native owner update06:05Z: corrected CODE B3/8d880c9f owns firstCI42452628804/Viewer128644899792, still testing. Latest genuine model proof05:58:58Z remains19/30. Old0231 is superseded. Minimal operational handoff658/e54 remains prepared for canonical-owner adoption at its CODE boundary; never insert it into an imminent ISSUE or replace active source588.
- Actual current numeric browser: readonly run42453486519/job128647460908 printed LIVE_OWNER_SITE_VERIFIED at06:12:24.744Z for Nov8/generation93/77 results/41 P1 groups. All12 numeric budget cases at320/390/1440, names, lifecycle, research return and rationale passed. The step then hit its unchanged4-minute timeout at06:12:25; final gate correctly failed the whole run. Preserve both the successful numeric observation and whole-run failure. Context alone took143 seconds; scope the performance correction to a read-only exact-commit shallow snapshot, pin both dates to one generation, preserve all authentication and prior-day checks, and prove unrelated ancestor objects are not fetched. No global/source transport change or timeout extension.
- Context performance implementation: authenticate the original checkout/remote before opening a private temporary bare Git repository. Fetch only required exact snapshots at depth1 and pin one parent for both dates; never probe the original checkout's partial-clone objects. MAC/tree/size/forecast-anchor checks, process-scoped Git auth and all browser assertions remain unchanged; temporary encrypted objects are cleaned up and publication methods reject. Implementer29, root29 and independent29 tests passed with zero skips; eight real-Git snapshot cases also passed on Git2.47.3. The regression demonstrates that a cached parent with a promised missing cipher blob cannot silently fetch unrelated ancestry. Actual live timing and whole-job success remain pending the next unchanged4-minute run.
