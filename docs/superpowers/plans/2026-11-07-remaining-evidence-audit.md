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
- [ ] Run synthetic CLI/privacy checks, review the diff, then publish using expected-head CAS.
- [ ] Read the completed actual job's count output and record confirmed causes.

## Continuation

The next repair plan is based on the actual count evidence, not an assumed cause. Existing normal BOAT run42376316340 was reserved once after the prior source's actual canonical record and receipts matched. Never restart it or duplicate the native probe.
