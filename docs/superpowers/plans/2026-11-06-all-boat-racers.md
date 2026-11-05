# All BOAT racers bulk intake implementation plan

> Execute with superpowers:executing-plans; tests first, independent final review.

Goal: load every racer in the official current term distribution, retaining actual coverage and source periods, then attempt GitHub-only encrypted handoff using the owner-configured key.
Spec: user's request 全選手のデータを入れて, original data-governance instructions, and docs/TEIAI_HISTORY_INTEGRATION.md.
Architecture: official single all-racer fan2604.lzh -> strict byte layout -> private in-memory SQLite -> AES-256-GCM checkpoint -> independent Actions readback. Reuse pinned PR64 safe LZH portable extractor and existing main checkpoint module. Existing predictions/models untouched.

Constraints: no Cloudflare/Vercel/new services/schedules. No per-racer API crawl or quota bypass. No production/test key substitution. No plaintext source, database or forecast artifact. Existing PR71 only. Latest term coverage is not all historical careers/current registration completeness. Future publication/availability unknown remains excluded from formal backtests.

Review focus: CP932 byte offsets; all records not first-row only; duplicate/conflicting revisions; zero samples vs measured zero; term period vs current age/class; absent owner key before network/artifact; restored encrypted bytes/hash and SQLite validation; no silent reinitialization of prediction history.

Task 1 — parse official all-racer term
- [ ] Write tests for complete fixed-length synthetic records, all 6 courses, scales, CP932 names, wrong period, duplicates, truncated/non-numeric rows and zero samples; RED.
- [ ] Implement race_ai/boat_racer_term.py; reuse portable archive parser with exact fan basename. Strict record layout 2014-2 onward. GREEN; parse real fan2604.

Task 2 — indexed all-racer database and provenance
- [ ] Write tests for all IDs, indexed lookups, immutable raw source/revisions, reimport idempotency, archive hash, availability/period gates and missing racers; RED.
- [ ] Implement race_ai/boat_racer_database.py with serialized SQLite and readback counts. Preserve original archive bytes privately inside DB; no original prediction database access. GREEN and actual full import/readback.

Task 3 — existing Actions + encrypted handoff
- [ ] Reuse main's scripts/keirin_github_checkpoint.mjs unchanged (generic SQLite encryption, scoped repo/generation/production key).
- [ ] Write offline CLI and encryption/secret absence tests; RED. Implement scripts/boat_all_racers.py with exact URL/hash, count-only stdout, no raw uploads.
- [ ] Add current request's intake/readback jobs to existing forecast-audit-ui.yml; no new workflow/cron. Missing key emits HOLD and no upstream GET; never synthetic success for real data.
- [ ] Run focused and full regressions, independent review, actual local term ingestion, PR71 push, exact HEAD CI and real job status.

Ledger: existing isolated worktree /workspace/race-ai-pr71. Updated from 5186fdb to ea3b5ac (docs-only concurrent change) before edits.
Ruling: use all racers in currently published official 2026-2 file as first complete population, not arbitrary numbered API requests. Full-career history is separate coverage; refusing to conflate reduces useful inputs until more verified data exists.
Ruling: user's repeated execution request authorizes direct implementation and existing PR/Actions changes. No additional design approval pause. Existing owner-key restriction remains binding.

Ledger update: Tasks1/2 implemented, actual1643 racers/9858 courses and full existing K1008 starts/621racers/1645union loaded, all1643lookups and serialized readback match. Source plaintext remains in private memory/workspace only.
Task3 implemented with existing codec and encrypted cache reuse. Focused20 tests PASS; real owner-key capture/readback pending Actions.
Independent review: three important findings fixed RED→GREEN (zero national samples, latest term membership/asof, A-B-A reversion stop). JST calendar and encrypted cache reuse also verified. Minor capacity limit8MiB documented; no promise of unbounded multi-term state.
