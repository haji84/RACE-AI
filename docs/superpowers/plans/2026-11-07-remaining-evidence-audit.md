# Remaining evidence audit implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Identify the actual retained-data blockers for the remaining eleven fits, BOAT result matching, and prospective evaluation without provider requests.

**Architecture:** Reuse the existing authenticated journal reader and owner-view reader inside the existing Actions production job. Pure count projections expose only fixed public vocabulary; they never alter originals or admit a source.

**Tech Stack:** Existing Python standard library, existing authenticated AES readers, existing GitHub Actions.

**Spec:** docs/superpowers/specs/2026-11-07-remaining-evidence-audit-design.md

## Global Constraints

- Current active models: 15 families/30 sport cells; seller remains retired.
- Keys stay in Actions. No plaintext private data in public files, logs or artifacts.
- Preserve originals, clocks, result revisions, frozen budget files/allocation and the 60-second boundary.
- No new provider requests, source cap changes, workflow/job/task/schedule/provider, payments, promotion, main merge or bets.
- Keep the separate native recovery owner boundary and all prior UNKNOWN accounting.

## Review Focus

- A reserved/unknown source count must remain null, never zero.
- An old rejected observation must not make a now-final race appear held.
- Unknown reason strings and private labels/URLs must never become output keys or values.
- A corrupted original index must fail rather than produce trusted-looking counts.
- Missing owner/Actions context must stop before artifact or owner-view reads.

### Task 1: Safe count projections

**Files:** scripts/boat_remaining_completion_audit.py; tests/test_boat_remaining_completion_audit.py.

**Interfaces:** audit_saved_view(view, *, now) and audit_journal(body) return count-only dictionaries, preserving their inputs.

- [x] Write tests for current holds, expired/future cutoffs, historical rejections, unknown counts, private-field redaction and index integrity.
- [x] Run tests and observe the missing implementation failure.
- [x] Implement the two pure projections.
- [x] Run the focused tests and existing result/prospective audit regression.

### Task 2: Actual Actions readback

**Files:** same audit script; audit/state/remaining-completion-audit-input.json; existing .github/workflows/forecast-audit-ui.yml.

**Interfaces:** main(argv=None) requires an owner Actions environment, verifies one explicit journal pin with the existing reader, reads the owner view, and emits one safe JSON summary.

- [x] Test Actions/owner guard before private I/O.
- [x] Add a prefix-gated step in the existing production job; no new job.
- [x] Run synthetic CLI/privacy checks, review the diff, then publish using expected-head CAS.
- [x] Read the completed actual job's count output and record confirmed causes.

### Task 3: Preserve result work after the last forecast window

**Files:** scripts/github_existing_cycle.py; tests/test_github_existing_cycle_startup_wait.py.

**Interfaces:** _restored_pending_result_count(day, now) reads the existing sealed restored continuity and counts unique forecast races without a confirmed ordinary/cancelled outcome. wait_for_window retains its existing SOURCE_WINDOW_READY gate when that work remains.

- [x] Reproduce the confirmed NO_FUTURE_WINDOW/zero-round stop with pending results.
- [x] Add result-work readiness without changing source/session guards, 90-second result wait, five-minute polling eligibility, original forecasts, or operational limits.
- [x] Verify pending, already-confirmed, absent/corrupt continuity, day/handoff and inherited wait boundaries.

### Task 4: Attribute the actual observation conflict without accepting it

**Files:** existing read-only audit script/input/tests.

**Interfaces:** audit_observation_conflicts(base, addition) returns only fixed field-name difference counts and same-source counts. The authenticated loader may read one explicitly pinned native continuity archive and project it using the existing reader.

- [x] Test same-clock field conflicts, identical replay, redaction and input conservation.
- [x] Add the actual completed source42376316340 continuity pin and count-only replay.
- [x] Expose known blocked-request reason/method counts from the already retained native browser index; unavailable projections remain null.
- [x] Read actual Actions counts before changing any observation merge rule or sending another native probe. The authenticated continuity comparison returned zero conflicts; the strict rejection was retained.

## Continuation

### Task 5: Inspect the actual rejecting pair, retaining the rejection

The authenticated continuity comparison returned zero conflicts, so it does not establish the cause of the actual feed exception. The latest native probe retained a DOM and required result response, then failed SOURCE_VALIDATION; it is no longer correct to describe that attempt as failing to reach the result UI.

- [x] Reproduce strict view rejection with safe fixed field-count evidence, without retaining private values in exceptions or changing acceptance.
- [x] Expose the actual exception's counts at the existing publisher's error boundary.
- [x] Add fixed native source-validation codes and required-role HTTP status counts.
- [x] Review and exercise the existing source-free display path once, adopting existing queued work and preserving every source/native owner guard.
- [ ] Repair only a cause established by actual count evidence, then verify retained-original readback.

### Task 6: Verify the explicit settlement day across midnight

Actual run42384768071 passed bounded original maintenance, published the authenticated source handoff mirror and strict encrypted-view generations31/32. Its final display check rejected SAVED_SITE_CURRENT_DAY_REQUIRED after JST changed to11/8 while the frozen settlement is11/7.

- [x] Reproduce the after-midnight failure without changing the actual clock.
- [x] Add explicit historical-day selection; retain strict current-day default and all future-forecast clock requirements.
- [x] Emit selected-day and actual-current-day scope separately; historical counts never become current-day counts.
- [x] Bind actual final evidence to the unchanged plan day, audit day and browser verification clock.
- [x] Review and verify the actual historical owner site at both existing widths. Source-free display42386374576 passed; live run42394941895 verified the compact private owner view at three widths, generation42 and129 November7 results. Latest run42398357632/job128480528315 independently verified generation44 with the Research audit at17:55:30Z, preserving the same129 November7 results and null current-day counts.

### Task7: Diagnose the three remaining holds using retained SP bytes

The actual November7 audit is129 final/132, with one600-second cutoff mismatch and two identity-unverified projections. Those rejection labels do not establish why the original SP parser failed.

- [x] Add a read-only authenticated intraday reader after the existing Actions/key/owner checks.
- [x] Bind each held result to the retained receipt's exact SHA, capture clock, official URL and race identity; never substitute an older or different capture.
- [x] Replay the supported SP parser and existing strict projection for fixed reason counts only. Keep original forecasts, allocations, holds and source clocks unchanged; authentication failure reports UNAVAILABLE.
- [x] Verify synthetic hash/privacy/receipt/ambiguous-cutoff cases and the real encrypted intraday restore contract:47 related tests pass, zero skipped; independent audit29 tests pass.
- [x] Integrate at an actual completed native-source/issuer boundary with an expected-head fast-forward. Completion-audit212f4dc1 changed no workflow or source authority.
- [x] Read actual retained-source reason counts before implementing any settlement correction. Production128541617986/run42418481443 verified allthree matching captures: RESULT_WINNER_INVALID2 and AVAILABLE1/RESULT_CUTOFF_MISMATCH1, no provider requests or admissions.

### Task8: Inspect supported payout syntax and every original clock

- [x] Add fixed payout-syntax classes after the existing exact receipt binding; never expose original tokens, combinations or amounts.
- [x] Dry-project temporary copies for each saved cutoff and separately count whether every forecast clock precedes every source/original cutoff. Keep the existing whole-row rejection and originals unchanged.
- [x] Verify privacy, malformed syntax, preserved ambiguous-cutoff hold and late alternate model clocks. Current33 audit tests pass; related settlement/restore tests remain passing and independent review is clear.
- [ ] Read actual syntax/chronology counts in the existing source-free production job.
- [ ] Correct only the demonstrated parser/eligibility defect and verify actual retained-result publication without weakening formal settlement.

The next repair plan is based on the actual count evidence, not an assumed cause. Existing normal BOAT run42376316340 was reserved once after the prior source's actual canonical record and receipts matched. Never restart it or duplicate the native probe.
