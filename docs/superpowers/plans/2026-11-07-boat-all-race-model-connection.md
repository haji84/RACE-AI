# BOAT all-race model connection implementation plan

> Parallel independent domains under superpowers:dispatching-parallel-agents; root integrates shared collector/feed and performs final verification. TDD and fresh final review required.

**Goal:** connect official active-entrant exhibitions and existing models to one saved forecast/result website with racer names.
**Spec:** `docs/superpowers/specs/2026-11-07-boat-all-race-model-connection-design.md`.
**Constraints:** GitHub only; unchanged original forecasts; no active worker stop/restart, new provider/permission/charge/main merge. All raw data and keys remain outside public Git/logs/artifacts; only encrypted private bundles may be published.

## Interfaces and ownership

1. Active entrant model support: `boat_ab_shadow.py`, `boat_live_feature_shadow.py`, `boat_observed_pairwise_models.py`, `observed_p1_connection.py`, `boat_multi_feature_models.py`, `boat_tactical_scenarios.py`, `frozen_day_cycle.py`, relevant new tests. Public model input rows contain only confirmed active entrants, count3..6, original physical lanes retained; full six-entrant outputs remain identical.
2. Source adapter: new `boat_official_program.py` + tests. `parse_program(raw, *, day, venue, race_no, source_url, captured_at)` returns pinned-compatible program shape plus explicit missing metadata/names/withdrawals; strict source identities retained. Does not mutate pinned sources or collector.
3. Model inputs/training: new `boat_all_model_inputs.py` + tests, owned generic four-sport model sparse path where necessary. `build_native_inputs(program, beforeinfo, *, as_of, history_context=None, fitted_model=None)` returns native payload groups and per-model missing reasons; actual source hashes/times retained. Reuse venue research modules, no duplicate pipeline.
4. Site union/names: new `boat_saved_model_view.py` + tests, `web/app.js`/`web/product-data.js` as needed. `merge_saved_views(base, additions, *, names=None)` unions saved forecasts without changing old prediction bodies; explicit participant registration binding for names. Does not own crypto/feed files.
5. Root: shared collector integration, history/fitted checkpoint restore/export, model-level persistence/coverage, feed append protocol/bootstrap/site build, encrypted real data activation and verification. Owns `scripts/boat_nationwide_ab_pilot.py`, `scripts/github_existing_cycle.py`, `saved_view_feed.py`, `saved_pages.py`, feed/browser crypto and workflow integration.

## Tasks
- [x] Each independent domain: read exact native contracts; write meaningful failing tests, implement, verify affected tests, report files/commands and limitations. No public/private payload printing or live source calls by delegates.
- [x] Integrate actual entrant selection and owned all-venue adapter; ensure ready family execution is not gated by unrelated models' missing inputs.
- [x] Connect verified historical inputs and real fitted artifacts; persist outputs with unchanged prior originals, stage and pre-cutoff receipts.
- [x] Unify existing and native forecast views, enrich racer names, evolve encrypted feed append semantics and preserve old originals.
- [x] Fresh review, whole affected suites and browser flows, real retained source replay, existing URL publication/readback. Preserve concurrent branch updates.
- [x] Record evidence and exact live/replay scope. New current-day exhibition collection must wait for actual publication rather than invent post-exhibition inputs at night.

## Bounded source handoff follow-up

Protect all native original and continuity uploads with the existing Actions-only
owner key before activating a successor. Preserve the actual GitHub outer ZIP
receipt and unchanged inner originals. A host supervisor must read only a
separate count-only control summary bound to the encrypted continuity, never
receive the owner key. Keep the deployed 240/45 requests, 24 rounds, 65-minute
source session and 180-second poll limits. An early worker may wait without
source requests for the authenticated first T-15 window, within its existing
physical handoff deadline, before starting its bounded session.

- [x] Encrypt all five native producer paths and integrate their readers.
- [x] Verify count-only host control compatibility and source-free startup wait.
- [ ] Review and deploy the exact follow-up, then record the actual source-worker
  state. Future exhibition inputs and prospective accuracy remain unproved
  until their genuine observations and pre-cutoff save receipts exist.

## Review focus
- A missing exhibition does not mean withdrawn; explicit source roster governs.
- Non-contiguous physical lanes and less than eight possible trifectas.
- Mandatory feature absence is not silently converted to an invented value or fitted status.
- Feed append adds models/days without deleting or editing previous original identities.
- Display name belongs to the actual registration, and all predictor/date/cutoff/source checks remain intact.
