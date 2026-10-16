# Tokuyama One-Day Worker Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline for this bounded task. No subagents, push, deployment, collection schedule, or publication.

**Goal:** Add a reusable one-request collector that stops before network access when factual ingestion rights are unknown and never mistakes an incomplete index for a publishable snapshot.

**Architecture:** Compose the existing rights registry, race index parser, verified-detail join, and publisher schema. A fixed-origin, bounded transport computes source provenance; date-bearing official race links must match all parsed races. Return structured failure/partial states without writing files or uploading.

**Tech Stack:** Python standard library; existing unittest suite.

**Spec:** Parent assignment plus `docs/all-24-venue-data-media-policy.md`.

## Global Constraints

- Keep factual ingestion and factual publication decisions separate; unknown remains unknown.
- Today is JST 2026-10-15 for the investigation. Runtime day uses an aware clock.
- No live collection with unknown terms; no actual source data committed, stored, or published.
- One GET only, 10 second timeout, 1,000,000 byte body cap, no redirects/retries.
- Existing parsers remain the authority for lane structure and verified detail joins.

## Review Focus

- Requested URL can be correct while body contains yesterday's races: require date-bearing race links.
- Unknown/duplicate/unrelated rights records must stop before invoking transport.
- Clock/day mismatch must stop before invoking transport.
- Oversized/error/redirected responses must never become normalized candidates.
- Missing identities/motors must stay partial; independently reviewed details are required for schema-complete candidates.

### Task 1: Collector and failure-state contract

**Files:** Create `race_ai/tokuyama_day_worker.py`, `tests/test_tokuyama_day_worker.py`, and `docs/TOKUYAMA_WORKER_STATUS.md`.

**Interfaces:** `collect_tokuyama_day(day, rights, now=None, transport=None, details=None) -> dict`; injected transport `(url, *, timeout, max_bytes) -> FetchResponse`. Complete candidates conform to `day_snapshot_publisher.validate` only when separately supplied publication approval is present; worker never supplies that approval.

- [x] Write synthetic tests for blocked rights/day, exact date links, partial/complete candidates, response bounds, and detail conflicts.
- [x] Run tests and observe missing-module failure.
- [x] Implement fixed endpoint/transport and collector using existing parsers.
- [x] Run targeted tests, then `python -m unittest discover -s tests -v`; inspect all failures.
- [x] Record primary-source observations and boundaries; self-review and commit locally.

## Execution ledger

Ruling: Parent explicitly requests continuous bounded implementation; no additional plan approval is needed. Local plan and status documentation are repository-backed artifacts.

Ruling: Expected manually reviewed per-day SHA is not required. SHA is computed at acquisition; body race-link dates prove requested race identity, while factual-use permission and independently verified details remain separate inputs.

Ruling: Rights may cover the fixed race-index collection page across dates, as well as an exact daily URL. An operator still needs independent permission evidence for that scope; no allowed production records are supplied. This avoids daily permission edits without broadening the collector to arbitrary pages.

Verification: 17 worker tests passed; full suite 178 tests OK with one existing OpenCV skip. The first publisher-compatibility run failed because the synthetic UTC clock was later than the real clock; fixture now uses 2026-10-14T16:00Z (JST 10/15), preserving the runtime future-observation guard.

Final self-review: fixed duplicate racer/motor acceptance and acquisition timestamp/midnight boundary via observed RED→GREEN regressions. No subagents were used per parent assignment. Rights-empty runtime dry run on actual JST 2026-10-15 returns SOURCE_RIGHTS_BLOCKED without transport access. No deferred findings; parent branch review remains required before integration.

Independent-review fix: global date links did not bind parsed race rows. Detached current-day navigation, lane-cell date links, and swapped row link numbers reproduced acceptance (three RED regressions). RaceLinks now inherits the existing TableParser and associates exactly one dated official race link with each race row's first cell. Targeted 20 tests GREEN; full suite 181 tests OK, one existing OpenCV skip. No real collection or permission changes were needed.
