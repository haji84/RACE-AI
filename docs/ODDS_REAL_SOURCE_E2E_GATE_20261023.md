# P0 live all-trifecta odds source + one-minute distribution acceptance gate

Date: 2026-10-23 JST. Governing [Issue #67](https://github.com/haji84/RACE-AI/issues/67).
Existing [PR #71](https://github.com/haji84/RACE-AI/pull/71) remains Draft and stacked on PR #69.
**No fresh live official odds ingestion, actual one-minute upstream refresh,
production deployment, or iPhone Safari live acceptance is claimed.**

## 1. First concrete candidate, not a blanket license

First-party BOATRACE example for 3連単:
`https://www.boatrace.jp/owpc/pc/race/odds3t?rno=10&jcd=08&hd=20260926`.

Verified from [the official page](https://www.boatrace.jp/owpc/pc/race/odds3t?hd=20260926&jcd=08&rno=10):
- One race page displays all **120 ordered 3連単 combinations** for six boats.
- [Official website about/update notice](https://www.boatrace.jp/owpc/pc/extra/about.html):
  current page odds do not refresh automatically; update is via the refresh
  control. Its displayed cutoff-time odds are NOT guaranteed final settlement
  odds, and later start-incident adjustments are not shown.
- [Official policy](https://www.boatrace.jp/owpc/pc/extra/policy.html)
  prohibits disruption by large-scale traffic; it does not specify an
  affirmative right to collect and republish per-race odds once per minute.
  Rights for machine acquisition, historical private storage and publishing
  whole-market odds have NOT been established.
- A public [HTML-parser research example](https://github.com/ryuriki/boatrace-v2/blob/main/scripts/scrape_odds.py)
  identifies a six-column `td.oddsPoint` layout under the second `div.table1`.
  This is a **reference to be corroborated against actual permitted original
  HTML bytes**; a third-party parser is not proof of the currently served DOM.

**IMPORTANT**: B-program/K-result day archives are ONE FILE/day; official
3連単 odds pages are currently **ONE PAGE PER RACE**. They are not the same
download or traffic budget. If 156 races each need 30 minute-by-minute
snapshots, the simple upper workload is ~4,680 odds page GETs/day **for
BOAT alone**, excluding retries and other sports, versus two B/K daily
downloads. This is a scenario, not measured consumption and not proof the
host allows that rate. No unlicensed national polling was started.

## 2. Implemented offline source-to-feed seam

- `race_ai/boat_official_3t_odds_adapter.py`:
  validates the exact first-party race URL, race ID/venue/day and separate
  official bet-sales cutoff. Accepts **operator-supplied UTF-8 HTML bytes**,
  pre-gated `PermissionPolicy` and a separately reviewed new
  `odds_display` rights purpose (in addition to private analysis/storage).
  Extracts all 120 cell values from the documented candidate table layout,
  maps 6 columns x 20 rows to exact ordered tickets, detects duplicates/
  truncations/layout changes, preserves temporarily missing odds as
  `UNAVAILABLE/null`. Does not parse/publish a current race result.
  HTML text/markup bytes from a current official race have not been independently
  tested here: synthetic HTML contract tests ONLY.
- `race_ai/boat_3t_odds_handoff_cli.py`: opt-in, **offline** conversion of a
  separately lawfully supplied single HTML snapshot to an exclusive mode-0600
  private JSON file outside Git. The HMAC reviewer policy alone does **not**
  create provider license rights; source/permission must be independently
  checked. No remote HTTP or public release. The CLI does NOT invent a
  provider update timestamp.
- `web/full-odds-model.js`: now explicitly allows
  `source_published_at=null` but shows a **stale/unverified provider time**
  warning instead of claiming a fresh live quote; 60-second client
  refresh does not change provider freshness.
- `race_ai/odds_refresh_plan.py`: deterministic offline one-minute planner,
  with deadline ordering, 60-second per-race cooldown, backoff, a separate
  `odds_display` right and explicit **persisted daily attempt-counter
  prerequisite**. Source-budget settings default to ZERO: this planning
  module fetches nothing. Quota-exhausted races remain visible as
  `CAPACITY_OR_DAILY_QUOTA_UNAVAILABLE`.
- Tests: `tests/test_boat_official_3t_odds_adapter.py`,
  `tests/test_boat_3t_odds_handoff_cli.py`,
  `tests/test_odds_refresh_plan.py`. They use fictional 2030 fixtures,
  NOT an actual official event or a real source permission.

### Separate guarded delivery storage

- `workers/odds_schema.sql`: D1 latest-quote table independent of
  immutable forecast and official result audit data.
- `workers/odds_feed_worker.mjs`: optional **protected preview** API
  `GET /data/odds/<race_id>.json` plus `POST /internal/odds`.
  Server-side validated full quote corpus, guarded preview flags, private
  ingest authorization secret, exact externally reviewed rights reference,
  server-side receipt time, canonical SHA-256 and readback. It never
  fetches provider pages, changes AI picks, or purchases tickets.
  Both read and write toggles default DISABLED. The actual external
  rights review must occur before the flags are set, and a protected
  preview/Access gate is required before deployment.
- `tests/odds_feed_worker.test.mjs`: mocked D1 tests and denial paths.
- `vercel.json` explicitly has `deploymentEnabled:false`. No Cloudflare
  D1/database creation, Worker upload, secrets changes, cron installation
  or production route activation was authorized by this code commit.

## 3. Why D1 instead of a naive per-race Workers KV free store

[Cloudflare Workers KV free pricing](https://developers.cloudflare.com/kv/platform/pricing/)
currently states **1,000 key writes/day**. If 156 races x 30 snapshots,
4,680 per-day writes would exceed that isolated free KV allowance. D1
[Cloudflare's current plan overview](https://www.cloudflare.com/plans/)
lists free tier **100,000 rows written/day and 5 GB storage** in aggregate,
subject to plan/account constraints. D1 is a more plausible candidate for a
bounded per-race latest-value store; these numbers are not a verified
all-sport cost estimate or proof that the external data provider allows
this polling. Workers Free CPU/requests, D1 reads, HTTP traffic, and
other use on the account must also be included in budgeting.

[Cloudflare Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/)
supports `* * * * *` scheduling. **Scheduling a minute trigger is not
the same as obtaining a new official odds snapshot every minute**. No
automatic provider Cron has been enabled in this PR. The UI's existing
minute timer only re-reads the same-origin URL after data arrives.

## 4. Still missing for a genuine live 1-race E2E

1. Audit **BOATRACE and the actual odds-hosting subsystem's** scope, rate,
   private retention, whole-market derivative quotation/public display,
   robots/technical controls, and any applicable legal exceptions.
   A shared signed internal policy is not independently authenticated
   upstream permission.
2. After rights review, acquire ONE current upcoming race's entire official
   odds HTML via a legitimately controlled single request. Store a private
   hash and inspect the *actual* `td.oddsPoint` DOM/120 ticket count,
   cancellations, exact official cutoff and **original provider refresh
   time if exposed**; reject layout changes.
3. Validate the resulting private JSON in Node UI `full-odds-model.js`;
   verify all 120 quotes against the official page for one race.
4. Provision protected preview D1 Worker and permitted ingest channel
   **only with explicit scope/budget/deployment approval**. Confirm one
   true authorized data update round-trip, external Worker/D1 stored receipt,
   browser read-back and source/update timestamp distinctions.
5. Test 60-second refresh for one race across repeated cycles, recording
   actual provider time, server receive time, browser read time, failure
   delays and byte/request budgets. 403/429 must stop/withdraw the
   provider poll, not increase its rate.
6. Compare preview forecast publication T-10 and independent freeze receipt
   to official closing time; separately verify settled result. Missing
   sources and unissued picks remain counted in full-day ledger.

**Any vendor that provides one properly licensed bulk multi-race odds feed
per minute is preferable to individually requesting all races from the
first-party public site if the latter exceeds permissible traffic or source
licensing terms.** The first pilot should be 1 race, not all events at once.

No paid subscriptions, unapproved production changes, public protected
odds publication, server Cron or automated betting in this work.
