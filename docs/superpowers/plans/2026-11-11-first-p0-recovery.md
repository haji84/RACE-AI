# Existing first P0 recovery implementation plan

**Goal:** Preserve run 42995325741 without regeneration, repair its receipt readback, and reconnect the existing production path to independent verification and the existing official-result scorer.

**Architecture:** Keep existing native P0/P1 models, first-receipt registry, AES codecs, private-original vault, saved view, and result scorer. Repair provenance/readback defects and connect existing readers as separate jobs in the existing main BOAT workflow. No new scheduler, source acquisition method, model, or scorer.

**Tech stack:** Python unittest, existing GitHub Actions, Git/Contents API, existing AES-GCM and HMAC state.

**Spec:** docs/RACE_AI_HANDOFF_20261111.md on main; the user's current repair request.

## Constraints

- Never regenerate or overwrite the first P0 or its existing index.
- Preserve artifact 13842474540 plus continuity 13842779131 and source control 13842973909.
- Public repository receives ciphertext and count/hash evidence only.
- Keep same-day source exclusion, request limits, 403/429 stops, and single-writer checks.
- Keep source run SHA e24f09f150e2318dd16a96bdc6db1d8c1317b9ae as historical provenance.
- Current production 997535d388e8dd6609355fde6f94e90307f818a3 already repairs several legacy-only reader checks; do not merge PR148 into its legacy base.
- CI success is not real-race completion; report authenticated originals, separate-runner reads, and official settlements separately.

## Review focus

- Successful receipt PUT followed by stale mutable-branch GET must use the actual creation commit; real tampering still fails.
- Missing or conflicting receipt/index, source SHA, companion, or vault locator must fail before publication.
- Production push/PR/foreign repository must not become an authorized source run.
- Failed source execution may contain valid saved originals, but it does not prove complete-day or P1 coverage.
- Readback job must use a distinct runner and the writer's exact vault commit; source-free recovery must not reach bootstrap or source acquisition.

## Task 1: Repair create-once receipt authentication

Files: scripts/first_p0_bootstrap.py; tests/test_first_p0_bootstrap.py.

- [x] Reproduce FIRST_RECEIPT_INDEPENDENT_READBACK_MISMATCH with a stale branch response.
- [x] Verify PUT content metadata and pin subsequent GET to returned creation commit.
- [x] Preserve existing-index no-overwrite behavior and fail on malformed or mismatching content.
- [x] Run focused first-P0 plus adjoining native receipt/AES tests.

## Task 2: Complete production provenance compatibility

Files: race_ai/boat_saved_result_recovery.py; race_ai/boat_source_control_mirror.py; their existing tests.

- [x] Reproduce rejection of valid production workflow_dispatch in saved-result reader.
- [x] Reuse authenticated_live_owner_run; keep repository, workflow, source SHA and clocks strict.
- [ ] Reproduce and fix equivalent branch-only source-mirror selection/state constraints.
- [ ] Test valid historical and production runs plus unauthorized event/repository/source mutations.

## Task 3: Connect separate-runner original verification

Files: scripts/boat_first_p0_readback.py; tests/test_boat_first_p0_readback.py; main .github/workflows/boat-racer-daily.yml.

- [ ] Reuse vault.capture for all three exact artifacts in one bounded transaction.
- [ ] Restore pinned locators on a distinct job; use native read_p0 and immutable receipt commit 20fc291429003fd0351baef4b0c1918b76b4e066.
- [ ] Verify matching original SHA, clocks, model/race identity, companions and count-only diagnostics.
- [ ] Test missing/foreign/tampered state before any publication.
- [ ] Use existing main trigger and runner permissions; no new workflow or cron.

## Task 4: Reconnect retained native predictions and official results

- [ ] Use existing private_cycle_restore/project_native_state/append_views/publication path with explicit-artifact coverage, preserving missing coverage.
- [ ] Reuse racer_intraday_refresh --replay-retained-results and --stage-existing-pdca; no provider requests during recovery.
- [ ] Align main release gate and workflow_run checks to reviewed production commit.
- [ ] Independently review changes, run relevant existing regression gates, and verify real Actions outputs.
- [ ] Record actual immutable evidence and remaining future-race/P1 gaps in handoff.

## Evidence ledger

- Original artifact outer ZIP SHA matches GitHub digest 8e9d92d2bfd9b2f73db881bd07619747c3498a647f6175ef7be56b56c8868d78.
- Companion ZIP SHA values also match current GitHub metadata.
- First receipt was committed at 20fc291429003fd0351baef4b0c1918b76b4e066; canonical 440 bytes, SHA256 749980a6cfa62f6588b938a254b887940cd54092d22a388d8d96516d05aa5161.
- Failed GET payload was not retained; stale/negative response is a hypothesis, while the ignored PUT commit and mutable read are observed code defects.
- Initial local vault test import failed because pinned parser packages were absent. Fetched the same immutable pr64/pr72 references used by Actions; baseline vault/workflow tests then passed 18/18.
