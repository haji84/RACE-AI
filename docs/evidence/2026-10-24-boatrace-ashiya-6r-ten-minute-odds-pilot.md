# 2026-10-24: 芦屋6R, official 3T odds within 10 minutes of sales cutoff

**Evidence status**: REAL_TWO_SNAPSHOTS_BEFORE_CLOSE; PRIVATE_FULL_120_D1_READBACK_PASS; EIGHT_SAMPLED_QUOTES_CHANGED; **NOT A CONTINUOUS 60-SECOND AUTO-POLL**, and no claimed independent user iPhone acceptance.

## Why this race

The owner observed that 芦屋7R's 11:35 close was too far away, and asked for a race with **no more than 10 minutes to the deadline**, hypothesizing that a not-yet-completed exhibition explained static odds.

Chose **2026-10-24 芦屋6R**, ID `20261024-21-06`, with the **official site's own cutoff table showing 11:05 JST**. Source:

`https://www.boatrace.jp/owpc/pc/race/odds3t?hd=20261024&jcd=21&rno=6`

The first real collection started 10:58:22.717 JST and completed **10:58:36.583 JST**, about **6m23s before the official scheduled sale cutoff**, matching the requested T-minus-10 criterion.

## Observations, not guesses

| Item | First official page | Second official page |
|---|---|---|
| Browser Run started (JST) | 10:58:22.717 | 11:00:18.731 |
| Source read completed (JST) | 10:58:36.583 | 11:00:28.746 |
| Official displayed `オッズ更新時間` | **10:57** | **10:59** |
| 3T `td.oddsPoint` cells | **120** | **120** |
| Numeric quoted cells | **120** | **120** |
| Source `.table1` blocks | **2** | **2** |
| Latest D1 source snapshot | First result only sampled in response; no full first payload saved | **All 120 saved with SHA-256 exact readback** |

The recorded first 8 odds vs second 8, in same DOM order:

| 3T exact ticket | T-6:23 sample | T-4:31 sample |
|---|---:|---:|
| 1-2-3 | 11.6 | 12.0 |
| 2-1-3 | 9.3 | 9.4 |
| 3-1-2 | 92.2 | 94.4 |
| 4-1-2 | 578.6 | 666.9 |
| 5-1-2 | 117.6 | 117.8 |
| 6-1-2 | 133.8 | 119.4 |
| 1-2-4 | 99.9 | 109.1 |
| 2-1-4 | 70.4 | 74.2 |

**All 8 of the available cross-snapshot samples changed; the total number of changed quotes across all 120 cannot be determined because the complete 120 first prices were not retained.** No additional measurements, missing combinations or price changes are invented. This is direct proof that actual odds can move in the final 10-minute window, and official publication time moved by two minutes. It does **not** prove that every race's source publishes fresh numbers at exactly one-minute intervals.

The separate official `beforeinfo` page for 6R was inspected once and contained a `スタート展示` label. Its actual exhibition completion time was **not** independently captured, so exhibition **causation** remains a plausible user hypothesis, not a proven event correlation.

## Actual Cloudflare results

- Used connected Cloudflare Browser Run's single-page scrape, limited to one race and necessary text selectors; no automated Cron or mass multi-venue scraping. Day/race-specific test quota table `odds_pilot_race_quota` was created and explicitly counted the first and second official odds reads as **2/3**. The different 7R pilot's existing UTC daily quota was left intact.
- After the second read, transformed the real DOM grid into 120 ordered combinations, validated unique tickets and nonmissing prices, created `RACE_AI_FULL_TRIFECTA_ODDS_V1` and saved to **private owner-only** D1 `race-ai-odds-private-preview`, table `odds_latest`. Appended SHA/time/count evidence in `odds_pilot_measurements`. No raw HTML/entire 120-price list was added to public GitHub.
- Full private payload SHA-256:
  `a9862ce973c8f3998ff4f6dfb82a7f9139d9efd1652522a9b58c23d1e7669500`.
- Verified D1 `payload_json` and `sha256` exactly matched what was written; the source was `odds3t?hd=20261024&jcd=21&rno=6`, `source_published_at=2026-10-24T10:59:00+09:00`, `ingested_at=2026-10-24T02:00:28.746Z`, 120 quoted of 120. The initial odds_latest index update reported **3 row writes** and the append-only measurement log reported **2 row writes**, not including other quota operations.
- Owner-only iPhone URL:
  `https://race-ai-odds-private-preview.qq-1130034.workers.dev/full-odds.html?race_id=20261024-21-06`
  The full-market UI uses same-origin JSON and existing 60-second refresh capability, but actual authenticated Safari display and repeated browser receipt count remain to be tested by the owner.

## Rate limiter and stop condition

An additional **Cloudflare Browser Rendering** request for comparing more exhibition pages returned **HTTP 429, code 2001 ("Rate limit exceeded")**. This identifies a *Cloudflare Browser Run API* rate limit, **not proof BOATRACE's own server issued 429**.

Consistent with the project fail-closed policy, the source experiment was halted at two successful 6R odds reads. We did not issue a third odds scrape or reattempt the Browser Run API after 429. The per-race quota table remains at **2/3**, and no automatic retry, new billing tier, Cron or external official data redistribution was enabled.

## Acceptance and remaining work

**Passed:** a real T-minus-10 eligible race with 120/120 exact 3T quotes; official source timestamp and actual odds values changed; full second snapshot persisted privately in D1 with correct SHA readback; one-race request cap enforced; current Worker remains owner-only.

**Not passed:** uninterrupted 60-second autonomous upstream polling; independent authenticated iPhone Safari observation; official exhibition timing causal analysis; final odds result reconciliation; current source rights for national always-on redistribution; measured source quota to support all four sports. Existing AI Top8 forecasts and prediction hashes were not touched; PR #71 remains Draft, and main is not merged.
