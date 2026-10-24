# RACE-AI P0: future one-race 60-second source → D1 → iPhone trial

Status: **RIGHTS_HOLD, NO_SCHEDULED_SOURCE_FETCH, NO_NEW_D1_WRITE** as of 2026-10-24 JST.
Governing [Issue #67](https://github.com/haji84/RACE-AI/issues/67), existing [Draft PR #71](https://github.com/haji84/RACE-AI/pull/71). This is not a new model or PR.

## One future race candidate, not automatic launch approval

- BOATRACE **2026-10-25 平和島 3R**, candidate source event identity `20261025-04-03`, 6 boats / 120 3T combinations. Official [10/25 schedule](https://www.boatrace.jp/owpc/pc/race/index?hd=20261025) lists 平和島開催. Search preview of official race index indicates planned **11:48 JST**, but direct event-specific official page was not accessible for independent read in this turn: **cutoff_verified=false until that exact date's race index or odds page is rechecked**. Stop without a verified cutoff.
- The [official site policy](https://www.boatrace.jp/owpc/pc/extra/policy.html) reserves content usage rights and prohibits disruptive large-volume access. It does **not** confer explicit 60-second automated retrieval, private retention, whole-120-quote owner-only redisplay rights. [Official about page](https://www.boatrace.jp/owpc/pc/extra/about.html) says browser odds pages do not auto-refresh. Neither is a machine-readable licensed 60s JSON provider feed.
- As of this review **NO VERIFIED RIGHTS/FEED CONTRACT** for a 60s normalized complete odds provider; therefore upstream automation is blocked and **no Cloudflare Cron or ingest flags were enabled**. A manually created feature flag is not provider authorization. An alternative transport requires independent legal/terms review.

## Existing capability + repaired cutoff race

- `workers/odds_auto_source_cron.mjs` has a disabled-by-default single-race candidate, bounded upstream JSON, 60-second durable lease, UTC hard budget, 403/429 stop, 120 quote schema and D1 SHA readback.
- This change closes a specific safety hole: if the request *starts* before cutoff but **finishes after**, do not write as a live race quote; log `CLOSED_DURING_PROVIDER_FETCH`. Synthetic test added.
- `race_ai/odds_three_cycle_audit.mjs` + tests verify separate minimum **three actual source attempt metadata records, three D1 persisted SHA readbacks, and three iPhone Safari timer read receipts matched to respective D1 ingested_at timestamps**, source/phone cadence, cutoff and rights/quota checkboxes. It is pure offline validation and does not authorize a provider.
- Audit result `METADATA_CONTRACT_PASS_NEEDS_INDEPENDENT_ATTESTATION` means caller-supplied metadata looks consistent, **not** that source rights or real delivery are proven. Synthetic 2030 data cannot be counted as a 2026 result.

## Independent acceptance and hold points

1. Obtain a verifiable upstream terms/license or separately reviewed applicable exception covering **1R GET per 60s**, private D1 retention, derivative all-120 display, and exact endpoint, including UTC request caps and retry conditions. Never imply public availability alone grants these uses.
2. Verify source response is a **permissioned full 120-tuple JSON feed** with publisher update time; the current Cloudflare Worker does not scrape HTML. Verify official future race and cutoff on the actual event date and handle changed cutoff/cancellation.
3. Verify all Cloudflare account-sharing apps' real Workers/D1/Browser Run daily usage and projected costs. API permission failure => UNKNOWN/HOLD. No paid plan or public release.
4. Inspect and backup existing D1, review non-destructive migration `workers/odds_auto_source_schema.sql`, get explicit owner approval prior to **any** change to production Worker/D1 or Cron.
5. Only after gates pass: enable protected one-race upstream 60s schedule with hard quota; store 3 successful source attempt receipts + D1 SHA readback, then 3 iPhone Safari timer receipts of **those same stored versions**. Success must be observed, not assumed because of a green CI.
6. Values may remain unchanged even with successful GET; distinguish source GET success vs new D1 quote version vs browser successful same snapshot. Such a case is not three novel quote updates. 403/429 should trigger backoff and a failed period.
7. Later scale to all four sports without changing the final T-10 freeze, 8-pick independence, results and PDCA goals.

No automated wagering, no new PR, no main merge, no general publication, no unapproved account charge or permissions change.
