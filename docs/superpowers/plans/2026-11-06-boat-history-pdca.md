# BOAT history and prospective PDCA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Privately collect official historical racer/motor facts, reconcile revised deadlines, and prepare unchanged-versus-history future comparisons.

**Architecture:** Reuse the existing strict B/K intake and model contracts. A private SQLite history store retains source revisions and dated facts. Evaluation derives a separate reconciled view; a standalone pair runner never changes old predictions or the active worker.

**Tech Stack:** Python stdlib, SQLite, existing pinned PR64 libarchive/LZH parsers, existing PR71 models.

**Spec:** `docs/superpowers/specs/2026-11-06-boat-history-pdca-design.md`

## Completion work authorized after overlap check

### Real-data acceptance continuation (owner: 「進めよ」)

- [x] Reuse an authenticated existing Nov6 result artifact to score the already frozenV2 pairs; preserve observations/revisions privately and publish counts only. No forecast regeneration or second official collector.
- [x] Add an opt-in production state publisher targeting only an encrypted-state ref in the same GitHub repository. Require the owner key before any Git mutation; preserve every generation and reject an absent existing ref without explicit initialization.
- [x] Add a pinned same-repository encrypted-state readback entrypoint to the existing CI. Missing key or encrypted input returns explicitHOLD/zeroGET. Only ciphertext and public metadata may be read/published, never plaintext state or keys.
- [x] Test wrongrepo/ref/hash/key/generation, missingstate, plaintext refusal, score replay and no secret logging using invented data; fresh review, full checks and existingPR publication.
- [ ] Complete real-data publication and a separate GitHub runner's authenticated restore after the owner key is bound to both environments. A HOLD or synthetic pass does not complete this item.

GitHub Secrets metadata request returned403 Resource not accessible by integration; do not bypass the denial or replace an unknown existing owner key. Cloud runtime has no owner-key binding. Implementation and local actual-data scoring continue independently of that missing credential.

Owner explicitly requested completion of steps 1–4 on 2026-11-06 JST. Keep the existing isolated worktree and PR71; preserve concurrent racer/video commits. Implement inline without another design confirmation.

- [x] Reproduce and fix malformed K membership loss. Preserve unresolved B-program opportunities separately from confirmed starts, retain V1 imports, add a parser revision, and replay cached archives without HTTP.
- [x] Reproduce and fix unequal cutoff revisions for learned rows. Only baseline-authenticated same-roster evidence may authorize a revision; validate both original and effective cutoff clocks.
- [x] Reproduce and fix late physical freeze admission. Record private create-once completion receipts bound to exact pair bytes; missing/late receipts cannot enter prospective metrics. Preserve old pairs.
- [x] Unify numeric history transformation with `observed_result_history._features`, already used by `teiai_feature_adapter`. Explicitly select one history source per comparison; do not chain two enrichers or count the same racer/race twice.
- [x] Add a complete private SQLite handoff for history, pair originals, physical receipts, result revisions and idempotent scoring; reuse the existing AES-GCM envelope. Production needs the owner-configured key. Missing state, wrong key, tamper and rollback must fail closed.
- [x] Verify the full flow with invented data in existing GitHub CI. Report synthetic verification and real-data operation separately; the real-data gate remains open above.
- [x] Run targeted and full checks, review the integration, preserve every original and publish code/counts/hash-only evidence to the existing PR. Never publish raw histories, forecast originals or plaintext state.

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

- [x] Add failing tests for later/earlier cutoff revisions, no revision witness, conflicting roster, late forecast and original-byte preservation.
- [x] Run targeted tests and observe the missing behavior.
- [x] Implement the minimal shared evaluation view and maintain original/effective-cutoff evidence.
- [x] Verify coverage and conditional aggregates use that same view, then replay Nov 5 local originals without altering them.
- [x] Commit code/tests/docs for this task.

### Task 2: Historical intake and profiles

Files: new `race_ai/boat_history_store.py`, `scripts/boat_history_collect.py`, `tests/test_boat_history_store.py`, `tests/test_boat_history_collect.py`.

Interfaces: `HistoryStore(path)`, `ingest_day(day, b_archive, k_archive, b_source, k_source)`, `racer_profile(racer_id, as_of)`, `motor_profile(venue, motor_no, as_of, epoch_start=None)`, `history_rows(racer_ids, as_of)`; collector generates official URLs only and resumes content-addressed private captures.

- [x] Add failing synthetic B/K parser-backed tests for profiles, ST/course facts, motor numbers, unavailable periods, duplicate intake, changed revisions, capture filtering and malformed source rejection.
- [x] Implement append-only source/day revisions and query only latest visible day revisions.
- [x] Add collector transport tests for 403/429/404, source identity, size limits and resume; implement backoff-aware sequential private capture.
- [x] Collect the initial real historical window and record aggregate counts/gaps only.
- [x] Commit code/tests and source-condition documentation, never raw data.

### Task 3: Prospective paired comparison

Files: new `race_ai/boat_history_comparison.py`, `scripts/boat_history_compare.py`, `tests/test_boat_history_comparison.py`.

Interfaces: `prepare_pair(snapshot, history_store, now) -> sealed_pair` and `score_pair(pair, observation, now) -> paired_summary`; baseline/history variants retain existing model IDs with separate variant identities.

- [x] Add failing tests for same-as-of/current-input pairs, capture-after-as-of, eight tickets, unknown actual course, immutability, tamper and result-before-freeze rejection.
- [x] Implement history-only snapshot enrichment using measured prior starts and complete source lineage; use unchanged existing weights.
- [x] Implement private write/read CLI and identical-result paired scoring, explicitly separating local claims from external freeze evidence.
- [x] Demonstrate actual profile/input readiness; label future results and model-superiority gates unfinished.
- [x] Run full available Python and Node suites, fresh review, fix important findings with tests and commit.
