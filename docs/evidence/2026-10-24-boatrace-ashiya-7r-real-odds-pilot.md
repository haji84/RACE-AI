# 2026-10-24 real BOATRACE odds: single-race private 120-way pilot evidence

**Status: REAL_FIRST_PARTY_ONE_RACE_SNAPSHOT_AND_D1_READBACK_PASS.**
**Not yet** a 60-second automatic provider update, iPhone Safari acceptance,
T-minus-10-min externally frozen AI prediction, official-result E2E or
authorization for public/mass reproduction.

## Source and exact verified race

- Race: **BOATRACE 芦屋 7R**, `20261024-21-07`, October 24, 2026 JST.
- Official entry and sales-cutoff reference:
  `https://www.boatrace.jp/owpc/pc/race/racelist?hd=20261024&jcd=21&rno=7`.
  The day's official cutoff table lists 7R **11:35 JST**.
- Direct full-trifecta odds page:
  `https://www.boatrace.jp/owpc/pc/race/odds3t?hd=20261024&jcd=21&rno=7`.
- Capture method: connected Cloudflare Browser Rendering **single-page scrape**,
  selector `td.oddsPoint` with `.table1` and rendered `body` for
  official page update time. One source call per observation. Embedded
  images/media/fonts/stylesheets were excluded. **No repeated nationwide
  scheduled crawl** was initiated.
- Real source validation: **2 table1 groups** and **120 td.oddsPoint cells**;
  all 120 cells were numeric/quoted with zero missing. The official
  page's own `オッズ更新時間` text read **10:36 JST**.
- Conversion: fixed six-lane row/column ticket mapping from the official
  20-row×6-column display, all 120 ordered triples and no duplicates.
  The actual raw HTML was *not* committed or republished to GitHub.
  This was a Cloudflare-side real DOM extraction and transform; it does
  **not** establish that the offline Python HTML parser has itself passed
  the identical live raw-HTML fixture yet.
- Resulting private schema:
  `RACE_AI_FULL_TRIFECTA_ODDS_V1`,
  `PROVIDER_REPORTED_UNVERIFIED`,`sales_status=UNKNOWN`,
  `source_published_at=2026-10-24T10:36:00+09:00`.
  The model's immutable eight picks were not touched.

## Three real limited checks and immutable hash audit

| Observation | Actual rendered official HTML obtained | Official published time | 120 quotes observed | Odds changed since earlier | Private D1 latest rewritten |
|---|---|---|---:|---:|---|
| 1 | 2026-10-24 10:40:01.352 JST | 10:36 JST | 120 / 120 | Baseline | yes |
| 2 | 2026-10-24 10:41:57.869 JST | 10:36 JST | 120 / 120 | 0 | no |
| 3 | 2026-10-24 10:43:21.569 JST | 10:36 JST | 120 / 120 | 0 | no |

Measured gaps between **completed observations**: **116.5 seconds** and
**83.7 seconds**. This verifies *repeated real upstream reads at least 60s
apart*, **NOT a completed precisely timed 60s autonomous Cron pipeline,
nor a source that publishes newly changing odds every minute**. The
source remained on its published 10:36 timestamp across all three reads.

- D1 (owner-only) `race-ai-odds-private-preview`, table `odds_latest`:
  **1 actual race** with exact 120-quote JSON, initial server-side
  `ingested_at=2026-10-24T01:40:01.352Z`.
- Full normalized payload SHA-256:
  `f0fde7b2e5e05e230a1ada1771955e3a8a61c6849b2371cfa4e36813e236fcc6`.
  The private D1 payload and SHA were read back and compared exactly
  immediately after writing. SHA recorded unchanged in all 3 audit rows.
- D1 `odds_pilot_measurements`: **3 append-only rows**, containing only
  first-party URL, real source publication/observation times, SHA and
  counts, **no replicated 120 odds payload in the public repo**.
- D1 `odds_ingest_quota`: **3 used out of a tool-enforced maximum
  3 manual source calls on 2026-10-24 UTC**. We explicitly stop here;
  the one-race live snapshot endpoint is not continuously polled.
- Real D1 write metadata from first `odds_latest` insert:
  **3 rows written** (including relevant index modifications).
  Subsequent unchanged-source checks performed **0 latest rows written**
  (the independent quota/audit counters still write metadata).
  This is the *pilot transaction observation*, not the complete
  account-wide Cloudflare billing ledger.

## Delivery and security

The already-running Cloudflare Worker
`race-ai-odds-private-preview.qq-1130034.workers.dev` stays protected by
Cloudflare Access with a single owner email and Worker-side verified
`ctx.access` identity. It reads `odds_latest` but cannot ingest the
official source on its own:
`ODDS_PREVIEW_INGEST_ENABLED=false`. The one-race snapshot was
**manually written through the owner's connected Cloudflare D1 API**;
it was *not* submitted through the disabled Worker write endpoint.

Owner-only iPhone test URL:
`https://race-ai-odds-private-preview.qq-1130034.workers.dev/full-odds.html?race_id=20261024-21-07`

Browser client is coded to check its own same-origin JSON every 60s, but
the owner's actual phone/Cloudflare Access login/rendering and received
timestamps have NOT yet been independently observed. Unauthorized visitors
must not see the data. The source's 10:36 publication time and the saved
10:40 ingestion must remain independently displayed, including stale
warnings, rather than be labeled automatically "latest" at 10:43.

## Permissions and scaling limitations

Only three bounded, manual, research-only reads of **one public official
page** were made. The official domain's `robots.txt` contains no
disallow path for this page; BOATRACE's website policy prohibits large-scale
traffic that disrupts operations and protects third-party content.
A public number/odds read does **not** establish blanket machine-download,
private resale, continuous 1-minute countrywide acquisition, or general
external redistribution permission. This pilot's owner-only access and
exclusion of raw HTML from public GitHub is **not** a general legal
license. Approval of a sustained source rate/whole-market publication
plan still requires a separate review.

The account's Billing/Usage API cannot be read with the existing connected
OAuth credential (403). Other GORIQ/AI-related Cloudflare services'
quota consumption therefore remains **UNKNOWN**, not zero. The current
D1 rows and three pilot requests do not establish 0-JPY all-sport operation.
No cost-increasing plan or Worker Cron was activated.

## What remains

1. Owner's actual iPhone Safari sign-in, full 120-quote screen and repeated
   client update checks from the protected URL above.
2. Verify publisher timestamps and the original Python adapter with an
   authorized official raw-HTML fixture. Keep all 120 values unmodified.
3. Owner-approved 60s trigger, durable bounded source quota and permitted
   future official odds source/republishing terms. Three manual checks
   are NOT 60s automation, and provider observations remained unchanged.
4. Record the actual other-project shared account usage and source
   concurrency before national four-sport expansion.
5. Independently frozen official forecast at T-10, official result
   reconciliation and measured Hit@8 remain separate unfinished goals.
