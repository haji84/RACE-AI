# P0 Git retention recovery implementation plan

**Goal:** Repair the observed storage stalls without changing prediction originals, models, source counters or permissions.

**Spec:** `docs/RACE_AI_BOAT_CODEX_HANDOFF_20261116.md`, the owner's 2026-11-17 continuation request, and the UI completion specification recovered from commit c15e683.

**Constraints:** Reuse PR292 for source and PR70 for main; no new PR, provider, workflow, model family, paid tier, public forecast or production weight switch. Preserve all existing histories. One producer only. CI success is not live completion.

## Task 1: Repair storage boundaries (inline execution)

- [x] Add local bare-Git regressions: a fresh partial vault writer must append without downloading an unrelated inherited blob, retain its exact tree ID, and let an independent reader restore it.
- [x] Observe RED; use a vault-only tree writer with promised objects permitted. Keep the normal state writer strict, SHA/AES readback and fast-forward CAS intact.
- [x] Add regressions for display/all-model fetch: obsolete ancestor-only bytes stay remote while exact old and new commits can both be restored on demand.
- [x] Observe RED; make only display/all-model pinned fetches shallow. Keep every explicit immutable pin reachable locally.
- [x] Run the existing vault, state, feed, model-store, source-refusal, continuity and JST handoff regressions. Review diff, publish only to existing PR292, check exact-head CI.

## Task 2: Verify actual operation and record limits

- [x] Recheck concurrent writers before any restart; read and authenticate failed continuity/source-control with the existing independent Actions gate.
- [x] Apply the reviewed storage repair and synchronize exact live source pins through existing PR70, preserving its proposal history. Never bypass branch protection.
- [ ] Verify a genuine successor, new encrypted P0/P1 receipts and independent AES readback. Record failures and unknowns separately; no retroactive forecast generation or counter reset.
- [x] Re-run the existing native Safari proof if ready. Desktop Safari does not satisfy physical iPhone acceptance.
- [x] Prepend actual SHAs, runs, test evidence and remaining four-sport/video/prospective gates to the latest status and handoff.

## Review focus

- A sparse append must not hydrate the historical ciphertext tree.
- Missing/corrupt requested originals must still fail independent readback.
- A concurrently advanced vault must retain strict CAS/ancestry checks.
- Shallow history must not turn a missing old pin into a reset.
- Failed metadata/auth/source refusal must not cause blind producer retries.

## Progress

Initial evidence: run43829249080 shows two STATE_GIT_FETCH_TIMEOUT, one all-model storage failure, and two VAULT_GIT_OPERATION_TIMEOUT. Local Git reproduces inherited-blob hydration specifically at write-tree; read-tree does not hydrate it. This establishes a mechanism, not retrospective proof of the exact stalled subprocess, which old logs did not identify.

PR292's published history was merged locally with current production; its JST tests and current production tests are both preserved. Unavailable b7380fe6/daae4c10 remain UNRESTORED.

Task 1 storage: complete at67200ef; 101 focused tests,159 owner regressions,75 independent reviewer tests; exact-head GitHub3 suites success.
Task 1 dependent recovery ruling: the latest actual failed bootstrap spent exactly1 B GET, so preserving the zero-request-only admission cannot fulfill live recovery. Add a separate AES/P0/first-receipt/vault-bound1-request schema; never relax generic idle recovery or reset usage. Independent reviewer46 tests and exact bare-vault3-original restore passed.
A local verification command initially named a nonexistent test_boat_recovery_trusted_events module; it was corrected to the actual test_boat_recovery_invocation module. No product defect was hidden by that command correction.

Task 1 source integrated: PR292 normally merged as82cedd7; reviewed d26b7ba tree matches. Bootstrap/owner179 passed; final exact-head CI3 suites success.
Task 2 main wiring: actual82 pins synchronized, c123 retained only for old original/control readback, current failed438292 audit selected, Safari reader missing parser dependencies reproduced and repaired (17 boundary tests pass). Main gate/audit/Safari101 and pinned reader64 pass. First local reader command mixed main and owner packages (SCHEMA_SPARSE import error); rerun used the workflow's whole-owner-package layout and passed. Source failures were not suppressed.

Task 2 live gate44017586294 failed safely; no successor and no vault write. Corrected the fixture to actual recover().attach_snapshots rows, reproduced receipt collision RED, applied the same immutable projection, and verified60 tests plus55 independent tests. Existing PR108 reused for this source fix; old44-factor proposal survives in ancestry but no coefficient/model change is applied. Existing PR100 will carry the next exact-main pin sync; no new PR.
Actual independent AES proof for priority438292 succeeded in44017586249/artifact14298594525. Later all-model scope replay in that job failed independently and is NOT a coverage success.

Task 2 live recovery: main PR100 merged df1ee16 after all source/main checks, source eff296 preserved. Gate44019424267 recovered three bootstrap originals without new GET/predictions and started owner44019591352. P0 vault step33 and round01 success; round02 active. New P0/P1/RESULT ZIPs independently downloaded and GitHub metadata SHA/size checked, not locally decrypted. New separate-runner AES/full coverage remains pending.
Actual Mac Safari44020668953 reached app_checks and failed APP_UI_CHECK_FAILED. Added only safe public checker location diagnostic; observed RED then18 tests GREEN and independent18 tests/no blockers. Reusing preserved PR208; no live source change or new producer trigger.
Round01 count-only audits disclose result-retention HOLD (native artifact clock) and prospective FROZEN_INPUT_REVIEW_REQUIRED; neither is reported complete.

Task 2 Safari diagnosis: PR208 normal merge cb3261d after23 exact-head checks (10 success/13 skipped). Actual Mac44022519670 failed at app_checks:560/driver.budget, after first-viewport native P1, model hashes, research return and result counts. New regression reproduces APP_UI_CHECK_FAILED when native Clear triggers an invalid-empty change and the app restores old budget. Corrected fixture's invalid port before the genuine RED; production correction uses native CMD+A/NULL release/replacement/Tab and preserves final checks.20 Safari tests GREEN, actual Mac pending; existing PR203 reused.120 existing video boundary tests passed, no real-video completion claim. Historical native retention pin13559236491 metadata now404; no expiry bypass.

Safari budget fix: independent20 tests/no blockers; PR203 exact23 checks complete (10 success/13 skipped), normally merged acd7c76 with tree equality. Actual retry44023534099 is pending. Owner round02 success05:21:47 UTC, round03 in progress; no new source pin or additional producer.

Actual Mac44023534099 again failed at app_checks:564/budget. The embedded Command chord was NOT a real Safari fix. Tightened the fixture to avoid assuming modifier semantics in Element Send Keys text, observed RED, then changed to standard /actions keyDown/up;21 tests and independent21 passed. Added failure-only allowlisted numeric budget/focus/valid fields, no DOM/secret/exception strings. Reusing PR194 for source-free Safari continuation, no producer/model changes.

Actual Mac44024956057 failed at app_checks:559/outlook element lookup, viewport unknown. It does not establish budget fix success or failure. PR182 adds bounded visibility wait and failure-only public module/line, page id, numeric viewport/error counts. Delayed-element RED then23 tests GREEN; corrected budget fixture's clock for the added lookup wait. Independent23 tests/no blockers. Source owner round03 succeeded05:40:01 UTC,04 active; no local owner key, new model, public asset deployment or producer restart.

Actual Mac44026515882: innerWidth390, page-races, JS errors0, app_checks:598. Requested viewport/iteration is not in the old report, so do not infer desktop-loop/budget completion. Candidate visible-click helper scrolls to center and requires its clipped center hit-test to identify the actual element/descendant before native click; blocked targets get no click. Native options unchanged, budget/pagination share protection.26 tests and independent26 passed; real Mac pending. Existing PR64 reused with immutable761 parser ancestry preserved and no mutable runtime branch references. No public product assets, source pin or weights changed.

Actual Mac44028066179/job133853102653 SUCCESS06:03:13Z on main36088f5d (reviewed38d2 tree match,23 CI checks complete). Safari26.6, actual1440/390 widths,4 model comparisons,2 P1/detail and2 result/budget views, final private boundary verified. Public assets unchanged; private loopback transport means browser AES/login, physical iPhone and8-screen visual acceptance remain false. Count-only report saved independently from authenticated job log. Owner rounds01〜04 success,05 active. Active main rules API200 confirms PR+unit required; classic protection endpoint403 retained as separate historical observation. Final status uses an existing docs PR, no new PR or guard bypass.
