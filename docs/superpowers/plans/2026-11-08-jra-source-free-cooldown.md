# JRA source-free cooldown implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Track the checks below before delivery.

**Goal:** Let the existing JRA source job finish its five CI dependencies during the required one-hour source interval, then wait without provider requests before normal admission.

**Architecture / design:** The JRA CLI's generation path alone gets a metadata-only waiter. All pinned prior runs must already be completed at entry. It derives the physical UTC boundary from actual pinned run and artifact metadata, sleeps at most 45 seconds per call, and has one fixed 3,605-second monotonic admission budget. An existing single-attempt GitHub read can remain in flight for up to 50 seconds; its return after the budget is always a HOLD. It refreshes every public fact at the boundary, then calls the unchanged generation path, including its complete MAC/history/denial, baseline, terms, once-only reservation and provider clock checks. The waiter grants no authority and writes no source/progress files. Readback and other sports do not wait.

**Approaches:** Publishing JRA only after the interval preserves current code but serializes another full CI cycle. Predicting CI duration can dispatch too early and leaves a HOLD. The selected bounded waiter overlaps existing CI and the interval, without changing either admission policy or any provider request limit. The parent agent authorized this implementation within the user's existing completion request.

**Tech stack:** Existing Python standard library and the existing GitHub Actions job; no new dependency, workflow, job, schedule, permission or cloud service.

## Constraints and interfaces

- Preserve legacy terminal UNKNOWN/cancelled records; do not require SUCCESS for all old runs.
- No synthetic clock, caller not-before, interval override, provider retry, key export or once-marker renewal.
- Check current-day terms, the existing 600-second margin plus the existing 100-second capture window, metadata expiry, pinned identity and owner run scope.
- Validate metadata initially and after the boundary; at most four complete snapshots (eight metadata reads per pinned journal) avoid exhausting the repository's GitHub API budget. A repeatedly changing prior boundary holds instead of extending the read budget.
- Reuse the existing fixed-host, single-attempt `MarkerTransport.json` reader; the generic `future.gh` path can retry transport failures and select archived receipts, so it is unsuitable for this scheduler.
- Fail closed on nonterminal metadata, malformed or mismatched facts, communication error, clock rollback, expired evidence, changed day, insufficient cutoff margin or exhausted monotonic budget.
- `wait_for_prior_window(manifest, env, *, reader=None, marker_transport=None, clock=None, sleeper=None, monotonic=None)` returns no acquisition authority. Dependencies are injected only for offline tests.
- Existing `common.environment()` already checks key presence; only the added waiter is key-free. Do not claim it runs before every existing key lookup.

## Task 1: Bounded metadata wait and CLI routing

- [x] Add authored metadata/clock tests in `tests/test_jra_future_source_wait.py`, including exact boundaries, final re-read, legacy UNKNOWN, nonterminal HOLD, changed prior facts, rollback, fixed budget, expiry/day/cutoff and no marker/source/file mutation. Observe RED before implementation.
- [x] Implement the waiter in `scripts/jra_future_source_capture.py` and route only its generation path through it. Preserve existing final status accounting, especially UNKNOWN on a possible interrupted capture. Do not edit historical issuer or cryptographic admission rules.
- [x] Test main routing: readback bypasses the waiter; waiting HOLD never calls generate; successful waiting calls unchanged generate once, whose fresh admission can still HOLD.
- [x] Change only the existing shared future source job timeout from 15 to 80 minutes and its contract expectation. Existing 15 minutes of source/readback work plus at most 60 minutes 5 seconds of waiting remains bounded; other scopes gain no waiting code.
- [x] Run the new waiter tests and focused existing JRA, future-history, once and workflow regressions. Expected: failures/errors 0; record exact counts and commands.
- [x] Obtain one fresh review of the complete delta. Address important findings with a failing regression first, then repeat only affected checks.
- [x] Commit locally for the parent to integrate after its current historical source boundary; do not push a shared ref or execute a live source.

## Review focus

- A prior rerun after the first snapshot must move the actual boundary or HOLD, never use stale completion metadata.
- A clock jump must not evade the monotonic bound or move a published source timestamp.
- Legacy UNKNOWN is preserved independently of whether its workflow conclusion was cancelled.
- Wait cancellation must never leave a false zero-provider final proof after generation starts.
- Existing global once marker, owner scope, source budget and full MAC/denial validation remain authoritative after waiting.

## Verified result

- New waiter tests first failed because the behavior was absent. Further RED cases caught the delayed UTC/monotonic anchor, missing CLI routing, unchanged 15-minute timeout and an API read storm (1,214 reads).
- The independent full-delta review found one P2: the generic GitHub reader retried a failed metadata read three times over 153 seconds and could select archived receipts. A default-transport regression reproduced the failure, then the existing single-attempt fixed-host transport made both HTTP 503 and timeout cases pass. No other important findings were reported.
- Final focused regression: **49 tests, 0 failures, 0 errors, 0 skipped; 55.537 seconds**. Modules: `tests.test_jra_future_source_wait`, `tests.test_official_future_source_workflow`, `tests.test_jra_future_source_capture`, `tests.test_all_existing_model_future_source_history`, `tests.test_all_existing_model_future_source_once`. `git diff --check` passed.
- This is authored offline metadata/clock and existing synthetic cryptographic regression evidence. No live provider request, owner-key use, source reservation, shared-ref push or GitHub Actions execution was performed for this delta. Full repository CI remains the integrating parent's next CODE verification.
- Operator sequence after integration: wait for the actual A/K workflow to be fully terminal, obtain its real pins, then publish the JRA request while the one-hour interval is running. The same five CI dependencies run first; the new waiter covers the actual remaining interval. It never waits for a nonterminal prior and never retries acquisition after a HOLD.
