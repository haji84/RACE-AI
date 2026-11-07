# Same-day race statistics implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. Existing native execution preference and publication authorization persist; one fresh whole-change reviewer at the end.

**Goal:** A confirmed first race changes the same athlete's card before their later race that day.
**Architecture:** Reuse the official day parser and the SP result endpoint's explicit course/ST/registration fields. Overlay verified per-race facts on the existing 90-day base, retain small encrypted SQLite delta packets, and publish aggregates with a lightweight status pointer.
**Tech Stack:** Existing Python/SQLite/AES-GCM, GitHub Actions/Pages raw delivery, plain JavaScript and existing Playwright/Node/unittest harnesses.
**Spec:** docs/superpowers/specs/2026-11-07-racer-intraday-design.md

## Global Constraints

- GitHub only; no new keys/providers/charges/security setting changes. Existing RACE_AI_STATE_KEY only.
- Original forecasts, all approved portraits and unrelated source work remain intact. No raw source/SQLite/key publication.
- Full SHA runtime pin; only the workflow goes to protected main through required CI and normal PR merge.
- Max12 official GET/run, at least1second between starts, persisted retry/denial waits. 5minute check target, not guaranteed webhook timing.
- Statistical window is explicitly past90days plus current-day confirmed results. No duplicated results at K reconciliation or retrospective scenario from later observations.

## Review Focus

- Same athlete runs twice; first result is present for the later cutoff, but never as the first race's prior input.
- Course changes, F/L/absence/cancellation and partial identity/ST must preserve real denominators and known/unknown distinctions.
- Newer raw response timestamps with unchanged facts must not double count or repeatedly copy the whole90day state.
- Partial publication/replay/normal revert/concurrent unrelated state writers cannot reset private state, regress public facts or overwrite UI/ciphers.
- Missing venue schedules, delayed source publication/403/429 and queue backlogs remain visible and cannot starve other venues.

### Task1: Official source facts and same-day aggregation

Files: create race_ai/racer_intraday_source.py and tests/test_racer_intraday_source.py; modify race_ai/racer_daily.py and its tests.
Interfaces: parse_result(raw,receipt)->{status,race_id,rows,deadlines,fact_sha256}; schedule(raw,receipt)->active venues; DailyStore.catalogue(...,extra_rows=(),live=None) emits backward compatibleV1 or explicitV2 with today metrics.
- [x] RED: explicit cs order differs from lane, F/L/absence, wrong body identity/future capture/partial finish, and pending response do not fabricate confirmed rows.
- [x] Implement bounded pure adapters using official dataheader/holdingheader/maindata identities and rlinklist deadlines. Compare an actual source with retained K facts privately.
- [x] RED: first result at10:10 adds once to the same registration/course for second race12:00; unchanged/revised result and next-day K replacement never double count. Implement overlay, today per-person records, and historical guards' metadata.
- [x] Run affected source/aggregate tests; commit.

### Task2: Incremental encrypted collection and publisher

Files: create race_ai/racer_intraday.py, race_ai/racer_intraday_handoff.py, scripts/racer_intraday_refresh.py and focused tests; modify shared history audit/publisher with backward compatible defaults.
Interfaces: advance(base,state,now,fetch,max_requests=12)->new private captures/state/coverage; restore/save journal on transfer ref; refresh(repo,private_dir,initialize=False) restores daily base and intraday index, advances facts, publishes typed aggregate/status receipts.
- [x] RED: bounded fair due queue, future races never fetched prematurely, persisted404/429/review waits, and atomic same-day replay.
- [x] Implement one dated official index/day, per-venue SP result/header bootstrap, due results before low-frequency revision checks, optional current K after21JST. Keep incomplete schedule coverage explicit.
- [x] RED: fresh runner restores small delta packets without unrelated blobs/whole90day copies; state cannot reset after corruption/missing/normal revert; CAS preserves other namespaces.
- [x] Implement AES-GCM SQLite packets with encrypted queue/index and new captures; namespace-HMAC head/ancestry audit. Retain original encrypted generations, resolve latest pointers, skip K-covered older packets.
- [x] RED: derived-only publication changes exactly the aggregate and status fixed paths, hash mismatch preserves previous browser data, retries can replay retained unpublished updates.
- [x] Implement atomic two-file publisher, normal UI/forecast publication inheritance, run affected Python tests; commit.

### Task3: Live card and bounded browser refresh

Files: web/racer-daily.js, web/racer-profiles.js, web/app.js, local/Pages/offline allowlists and related Node/browser tests.
Interfaces: V1/V2 parse; status pointer polling60seconds while visible, full aggregate fetch only when SHA changes; reference API exposes intraday asOf and per-person current-day records.
- [x] RED: before/after first-race update, correct course metrics, insufficient samples, same-day later cutoff allowed / closed earlier race withheld, stale/hash disagreement and synthetic identity isolation.
- [x] Implement explicit past90days+today labels, current-day result count/list, last result/last check/waits, six-course reference and current-period strengths.
- [x] Verify fixed endpoints/omitted credentials, offline no-network embedding, legacyV1 support and API validation; run full affected Node suite and existing profile/explorer/Crypto/offline browsers; commit.

### Task4: Verified publication and schedule correction

Files: existing .github/workflows/boat-racer-daily.yml, docs/RACE_EXPLORER.md, this plan and public counts-only evidence.
- [x] Fresh whole-change read-only review; one targeted TDD correction pass, then affected checks. Pending results now precede confirmed revisions; postponed targets respect their new cutoff. RED then18 affected tests GREEN.
- [x] Preserve concurrent source updates and publish only reviewed UI assets while retaining all cipher/image bytes.
- [x] Explicit source marker initializes only the new stream; actual Actions verifies current official facts, ciphertext and public SHA. Normal restart verifies retained replay.
- [x] Existing workflow gains bounded daytime5minute cron, keeps06:20 K reconciliation, defaults dispatch to intraday and uses full runtime SHA. Normally merge only workflow PR after required CI.
- [x] Verify actual main run, live card across3widths, same-day test flow and source coverage/limitations. Record exact run/commit/SHA receipts and finish docs.

Acceptance receipts: main PR86 merged normally after required CI; source initialization42381661383, main retained restart42381861735 and quiet replay42382190189 succeeded. Public catalogue74e43c8dfc73cb045aca0da5ae47856c7d91f81f2e2e59b0fb3b99582c6ae285; current-day132/132,1669 profiles,294 same-day two-start profiles; actual live browser320/390/1440 passed. Quiet replay0 GET/new captures, generation2 reused, only small status updated. Forecast ciphers7 and portrait assets57 unchanged. Actual future same-day second-start observation remains unobserved because activation was after racing; chronological fixture tests establish the implemented transition. Full project broad run/feature CI are not claimed passed; exact scope and outstanding state are in evidence.
