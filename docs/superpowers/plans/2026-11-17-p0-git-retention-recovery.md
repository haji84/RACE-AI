# P0 Git retention recovery implementation plan

**Goal:** Repair the observed storage stalls without changing prediction originals, models, source counters or permissions.

**Spec:** `docs/RACE_AI_BOAT_CODEX_HANDOFF_20261116.md`, the owner's 2026-11-17 continuation request, and the UI completion specification recovered from commit c15e683.

**Constraints:** Reuse PR292 for source and PR70 for main; no new PR, provider, workflow, model family, paid tier, public forecast or production weight switch. Preserve all existing histories. One producer only. CI success is not live completion.

## Task 1: Repair storage boundaries (inline execution)

- [ ] Add local bare-Git regressions: a fresh partial vault writer must append without downloading an unrelated inherited blob, retain its exact tree ID, and let an independent reader restore it.
- [ ] Observe RED; use a vault-only tree writer with promised objects permitted. Keep the normal state writer strict, SHA/AES readback and fast-forward CAS intact.
- [ ] Add regressions for display/all-model fetch: obsolete ancestor-only bytes stay remote while exact old and new commits can both be restored on demand.
- [ ] Observe RED; make only display/all-model pinned fetches shallow. Keep every explicit immutable pin reachable locally.
- [ ] Run the existing vault, state, feed, model-store, source-refusal, continuity and JST handoff regressions. Review diff, publish only to existing PR292, check exact-head CI.

## Task 2: Verify actual operation and record limits

- [ ] Recheck concurrent writers before any restart; read and authenticate failed continuity/source-control with the existing independent Actions gate.
- [ ] Apply the reviewed storage repair and synchronize exact live source pins through existing PR70, preserving its proposal history. Never bypass branch protection.
- [ ] Verify a genuine successor, new encrypted P0/P1 receipts and independent AES readback. Record failures and unknowns separately; no retroactive forecast generation or counter reset.
- [ ] Re-run the existing native Safari proof if ready. Desktop Safari does not satisfy physical iPhone acceptance.
- [ ] Prepend actual SHAs, runs, test evidence and remaining four-sport/video/prospective gates to the latest status and handoff.

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
