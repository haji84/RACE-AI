# BOAT history and prospective PDCA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Privately collect official historical racer/motor facts, reconcile revised deadlines, and prepare unchanged-versus-history future comparisons.

**Architecture:** Reuse the existing strict B/K intake and model contracts. A private SQLite history store retains source revisions and dated facts. Evaluation derives a separate reconciled view; a standalone pair runner never changes old predictions or the active worker.

**Tech Stack:** Python stdlib, SQLite, existing pinned PR64 libarchive/LZH parsers, existing PR71 models.

**Spec:** `docs/superpowers/specs/2026-11-06-boat-history-pdca-design.md`

## Global Constraints

- No BOATERS scrape, Cloudflare/Vercel, new service/workflow, fees, bets, baseline overwrite or automatic promotion.
- All actual data outside Git checkout in mode-0700 private directories; no plaintext public branch/artifact/cache.
- Preserve actual capture time, source revisions, and unknown/missing/exceptional states.
- Current source approval authorizes the user's requested personal-history task, not source republication.

## Review Focus

- Earlier revised cutoff cannot admit a late original; disagreements in racer identity quarantine the race.
- A malformed historical race/day cannot silently become a zero, duplicate sample or dropped denominator.
- Date-only K timestamps cannot stand in for B's actual printed deadline, or for capture availability.
- Reused motor numbers cannot silently become lifetime identities.
- Historical candidate inputs must be the only baseline/candidate difference, with equal information time and immutable result-independent originals.

### Task 1: Reconciled evaluation

Files: `race_ai/frozen_day_cycle.py`, `race_ai/all_race_top8_target.py`, `tests/test_boat_cutoff_revisions.py`.

Interface: existing `evaluate(rows, observations)` derives schedule-revision evidence from verified same-roster P1 rows in the same supplied batch; original inputs remain unchanged. Keep `settle` strict.

- [ ] Add failing tests for later/earlier cutoff revisions, no revision witness, conflicting roster, late forecast and original-byte preservation.
- [ ] Run targeted tests and observe the missing behavior.
- [ ] Implement the minimal shared evaluation view and maintain original/effective-cutoff evidence.
- [ ] Verify coverage and conditional aggregates use that same view, then replay Nov 5 local originals without altering them.
- [ ] Commit code/tests/docs for this task.

### Task 2: Historical intake and profiles

Files: new `race_ai/boat_history_store.py`, `scripts/boat_history_collect.py`, `tests/test_boat_history_store.py`, `tests/test_boat_history_collect.py`.

Interfaces: `HistoryStore(path)`, `ingest_day(day, b_archive, k_archive, b_source, k_source)`, `racer_profile(racer_id, as_of)`, `motor_profile(venue, motor_no, as_of, epoch_start=None)`, `history_rows(racer_ids, as_of)`; collector generates official URLs only and resumes content-addressed private captures.

- [ ] Add failing synthetic B/K parser-backed tests for profiles, ST/course facts, motor numbers, unavailable periods, duplicate intake, changed revisions, capture filtering and malformed source rejection.
- [ ] Implement append-only source/day revisions and query only latest visible day revisions.
- [ ] Add collector transport tests for 403/429/404, source identity, size limits and resume; implement backoff-aware sequential private capture.
- [ ] Collect the initial real historical window and record aggregate counts/gaps only.
- [ ] Commit code/tests and source-condition documentation, never raw data.

### Task 3: Prospective paired comparison

Files: new `race_ai/boat_history_comparison.py`, `scripts/boat_history_compare.py`, `tests/test_boat_history_comparison.py`.

Interfaces: `prepare_pair(snapshot, history_store, now) -> sealed_pair` and `score_pair(pair, observation, now) -> paired_summary`; baseline/history variants retain existing model IDs with separate variant identities.

- [ ] Add failing tests for same-as-of/current-input pairs, capture-after-as-of, eight tickets, unknown actual course, immutability, tamper and result-before-freeze rejection.
- [ ] Implement history-only snapshot enrichment using measured prior starts and complete source lineage; use unchanged existing weights.
- [ ] Implement private write/read CLI and identical-result paired scoring, explicitly separating local claims from external freeze evidence.
- [ ] Demonstrate actual profile/input readiness; label future results and model-superiority gates unfinished.
- [ ] Run full available Python and Node suites, fresh review, fix important findings with tests and commit.
