# Saved result reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline.

**Goal:** Reconcile all available finished races on the existing private site, preserving every prediction and result revision.

**Architecture:** Retain cumulative result observations and authenticated raw result captures in an append-only private viewer journal. Reuse the pinned official identity/schedule/DOM parser, with an owned result-only adapter for explicit cancellation and finish/payout facts that do not require every start-time or unrelated betting market. Project the latest observation with explicit reasons and coverage.

**Tech Stack:** Existing Python SQLite/HTML parsing, Node/Playwright, AES-GCM and GitHub Pages.

## Root causes and constraints

- Published snapshot held only30 final results from11:57 JST; completed later artifacts contain additional results.
- Constant12-race cancellation headings use a CSS class the legacy result parser does not read. Four other races lack full start-time rows, which are not needed to bind six finish identities. A malformed unrelated market can block a valid trifecta.
- Eleven official result schedules are60s later than the morning original. Shared strict scoring stays unchanged. The viewer may show a clearly labelled reference comparison only for a newly retained raw official page with matching date/venue/race/six racers, offset no more than60s, capture after both cutoffs, and original physical freeze before both. Never change original timestamps, Top8, hashes or formal eligibility.
- Explicit selected-race cancellation is different: no six finish records exist, and the cancelled page can carry a replacement timetable. A raw-bound cancellation heading may refund the original hypothetical plan after its original cutoff, with the original forecast frozen before that cutoff. The changed schedule is retained and labelled; it cannot authorize a normal result or a real purchase.
- Reuse existing artifact metadata/digests/CRC first. The explicit result-only reconciliation task has at most40 official GETs, one per unresolved past race with one later observation after10minutes if still unpublished, no HTTP-error retry, no worker restart/configuration or new workflow. Stop on HTTP errors, no data fabrication. Upcoming or unpublished results remain distinct from invalid observations.
- GitHub only; plaintext/private keys stay outside public Git/logs/artifacts. Preserve all800/1,000-yen financial logic and the existing owner URL.

## Review focus

- Cross-race/date/roster, inconsistent payout/finish and malformed source facts must never settle a ticket.
- Cancellation must come from a selected official race heading; incidental text or blank payout tables are not cancellation.
- A later invalid/pending observation cannot fall back silently to an older winning result.
- Clock-offset reference binding cannot rescue late forecasts, cross-day schedules, offsets over60s or non-raw source claims.
- Retain every history version; importing a duplicate is idempotent and conflicting capture identity stops the import.

### Task1: Retention and result-only source adapter

Files: new `race_ai/saved_result_sync.py`, `tests/test_saved_result_sync.py`; modify `race_ai/boat_pdca_projection.py`.

- [x] RED→GREEN synthetic source cases for cancellation, missing starts, unrelated-market placeholders, explicit refunds and bad identities/payouts.
- [x] RED→GREEN append-only merge, late/invalid latest observation,60s source-bound reference gating and original invariance.

### Task2: Coverage, private synchronization and delivery

Files: `web/app.js`, focused browser tests, existing viewer docs.

- [x] Display last synchronization, cancellation, clock-reference notes and per-race pending/rejection reasons without weakening official gates.
- [x] Independent read-only review and meaningful existing financial/crypto/browser regressions.
- [ ] Import all verified archives/cached raw pages into a private copy; independently verify every original, latest result, budgets and counts.
- [ ] Update the existing encrypted Pages snapshot under an exact parent and verify the live owner URL; report remaining upcoming/unpublished cases honestly.
