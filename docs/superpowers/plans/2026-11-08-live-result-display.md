# Live result matching and ordinary race detail implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. Existing native execution/publication authorization persists. One fresh whole-change reviewer at the end; no implementer agents.

**Goal:** Confirm published race results against saved predictions promptly and make the phone detail screen readable without exposed audit internals.
**Architecture:** Share the existing bounded SP queue with a result-only encrypted feed bridge. Preserve all forecast originals and formal eligibility, retain settlement deltas separately from athlete aggregates, and let the existing browser feed refresh show a compact outcome-first detail.
**Tech Stack:** Existing Python/SQLite/AES-GCM/GitHub Actions/Pages, plain JavaScript, unittest/Node/Playwright.
**Spec:** docs/superpowers/specs/2026-11-08-live-result-display-design.md

## Global Constraints

- GitHub only, existing owner key, no security/permissions changes/new charges/bets/provider substitution.
- Max12 official GET/run, starts at least1second apart, existing per-host/per-URL source waits remain effective.
- Preserve originals, saved cutoffs, private history, all portraits and official scoring gates. Publish ciphertext and derived counts only.
- No model intake/generation/original maintenance in result-only refresh. Result display references never become formal eligible scores.
- A5minute GitHub check plus60second browser read is a target, not a seconds-after-finish guarantee.

## Review Focus

- Payout/refund-only corrections change settlement identity even when finish/course statistics do not.
- K reconciliation or JST rollover never deletes a retained but unpublished settlement capture.
- Current and previous saved dates, including month boundaries, do not starve new results or forget overdue results.
- Concurrent feed changes reject safely, retain new source packets, and replay against the newest predecessor.
- Phone defaults hide raw IDs/codes/SHA while synthetic data and genuinely unavailable results remain clear; drafts/model choices survive refresh.

### Task1: Strict SP settlement adapter and shared result queue

Files: create `race_ai/boat_sp_settlement.py`, `tests/test_boat_sp_settlement.py`; modify `race_ai/saved_result_sync.py`, `race_ai/saved_view_feed.py`, `race_ai/racer_intraday.py`; add `tests/test_racer_result_queue.py`.
Interfaces: `parse_settlement(raw,receipt,now)->observation`; `settlement_digest(observation)->hex`; `IntradayState.advance(...,result_targets=())` shares max12 budget and retains `settlement_captures` independently; PC parse remains compatible.
- [x] RED tests for real-shaped strict identity/top3/payout/refund/absence/dead heat/cancellation/pending; wrong payload/future/contradictory winners rejected.
- [x] Implement SP dispatch in `parse_capture` and URL mapping in `F.update_view`. Add raw-bound SP schedule-change display reference with full roster/pre-both-clock gates; formal false.
- [x] RED queue tests: pending settlement despite canonical K, new results before revisions, payout-only revision, prior date/rollover retention, no future fetch, total budget/waits.
- [x] Implement optional target queue and capture digest; check before07JST avoids unnecessary new-day schedule discovery during previous-day catchup. Run `python -m unittest tests.test_boat_sp_settlement tests.test_racer_result_queue tests.test_racer_intraday tests.test_saved_result_sync tests.test_saved_view_feed`; commit.

### Task2: Result-only feed bridge and production runtime

Files: create `race_ai/racer_result_bridge.py`, `tests/test_racer_result_bridge.py`; modify `scripts/racer_intraday_refresh.py`, `race_ai/racer_daily_handoff.py`, existing workflow; extend end-to-end tests.
Interfaces: `SavedResultBridge(repo,now,...)` opens existing bootstrap/current feed and enumerates latest two saved dates; `.targets()` feeds Task1; `.publish(state,now)` applies retained captures against fresh predecessor, no new prediction work. `refresh(...,sync_results=False)` opt-in CLI `--sync-results` used by workflow. `publish_daily_catalogue(...,result_sync=None)` adds typed counts/check status to existing small status path.
- [ ] RED tests: pending→final→HIT/MISS projection, payout revision, two dates/month boundary, K removal survival, quiet no-generation, CAS replay and original inventory unchanged using real temporary Git/encryption.
- [ ] Implement bridge with fixed imports/config, bounded dates, per-race rejection isolation and no source/model/original-maintenance calls. Preserve earlier state when feed errors; expose only safe state/counts to public pointer/report.
- [ ] Save encrypted packets before feed publication, acknowledge only verified commits, and persist acknowledgements without losing captures. Morning reconciliation remains bounded and recombined; no V1 overwrite.
- [ ] Run affected Python integration suite and publisher tests; commit.

### Task3: Compact phone detail and honest result status

Files: `web/app.js`, `web/index.html`, `web/style.css`, related browser/Node tests.
Interfaces: Japanese display model names separate from internal identities; compact result view with combination/outcome/update time; collapsible audit details; manual read-only refresh uses existing encrypted feed polling and optional result status heartbeat.
- [ ] RED browser reproduction of screenshot: びわこ1R missing result + internal model/version/raw missing codes, large hero and SHA. Assert expected visible compact detail after update at320/390/1440px.
- [ ] Implement concise header and selection, result before long sections, no duplicate forecast rail, collapsed raw/evidence, friendly wait/review text, synthetic marker retained. Keep model switching, athlete cards, original identities and drafts.
- [ ] Verify result update without reload through actual WebCrypto fixtures, error/quiet preservation, selected model/day and editable budget retention. Run affected Node/explorer/Crypto/offline browsers; commit.

### Task4: Review, publish and verify real same-day reconciliation

- [ ] One fresh read-only whole-change review; one targeted RED→GREEN correction pass.
- [ ] Publish reviewed UI assets preserving all ciphertext/portraits and dynamic data. Preserve concurrent source commits.
- [ ] Source trigger runs new result-only synchronization on existing owner secret, then normal restart verifies retained replay/public SHA and actual saved-result counts. No namespace reset.
- [ ] Normally merge a workflow-only main PR after required CI with full runtime SHA pin and `--sync-results`. Verify main dispatch, live phone detail/result flow, owner-key-free browser context and count-only evidence. Finish docs/PR71 metadata without merging unrelated draft work.
