# RACE-AI: zero-additional-charge pilot and shared Cloudflare free-tier budget (2026-10-24)

**Owner's adopted direction:** Forecast **all four sports / all eligible races** using GitHub Actions; keep the AI Top8 locked by the T-10-min user-visible deadline; show **all trifecta combination odds**; refresh available full odds **once per minute only for races inside T-60 minutes**; keep heavy inference off Cloudflare. Begin with ONE real, authorized BOATRACE race before widening source rate/Cloudflare budget.

This is a **scenario and guard**, not a promise that full national minute-odds operation will stay free or that a permitted live data provider is available. The source-license, historic-data, external receipt, iPhone acceptance and result reconciliation gates remain unchanged. No automatic wagering.

## Verified platform limits (official Cloudflare)

- [Workers Free limits](https://developers.cloudflare.com/workers/platform/limits/): 100,000 Worker requests per **account** per UTC day; 10ms CPU time per invocation. Worker-scope cache hits still consume a Worker request (they may reduce CPU/D1); static [Cloudflare Pages assets served without Functions](https://developers.cloudflare.com/pages/functions/pricing/) are not charged against the Worker request cap.
- [D1 Free pricing](https://developers.cloudflare.com/d1/platform/pricing/): 5,000,000 database rows read/day, 100,000 rows written/day and 5GB combined database storage. Indexes affect row-write counts. [2026-09-01 enforcement](https://developers.cloudflare.com/changelog/post/2026-09-01-d1-free-tier-limit-enforcement/) means D1 operations can stop once the Free quota is exhausted.
- Limits are **shared with the user's other Workers/D1 projects**. Billing/usage API did not grant read permission in this ChatGPT connection; the current other-project usage remains UNKNOWN and must NEVER be represented as zero or as a real cost guarantee.

## What is actually implemented (existing Draft PR #71)

1. `race_ai/free_tier_budget.py` estimates a day's potential requests, D1 reads/writes and latest-data storage. The default **self-imposed target is only 60%** of the published shared-account Worker and D1 quotas to preserve possible capacity for other Cloudflare apps. It blocks a `PASS_ESTIMATE_ONLY` result if any other-app counter, external rights status or source request allowance is UNKNOWN; even a numerical pass **is not permission to deploy** or proof of 0 JPY billing.
2. Existing `race_ai/odds_refresh_plan.py` uses the owner's T-60 minute target (formerly T-40), while `minute_limit=0` and `daily_limit=0` stay unchanged until genuinely authorized. It does not automatically call outside sites, infer an official release time or silently drop races which missed updates.
3. `workers/odds_feed_worker.mjs` staged private ingest now **requires BOTH**:
   - Exactly one configured pilot `ODDS_PILOT_RACE_ID` and a separate explicit `ODDS_PILOT_MAX_UPDATES_PER_DAY` integer between 1 and 120; the first-stage Publisher enablement flag and credentials still default OFF.
   - A persistent SQLite quota table, `odds_ingest_quota` in `workers/odds_schema.sql`. A server-side UTC-day atomic `INSERT...ON CONFLICT...UPDATE...RETURNING` counts each authorized ingest even if its final JSON write fails. Once spent, it returns HTTP 429 rather than silently exceeding the cap. It also rejects second writes to the same race within 60 seconds (separate from user read checks).
   - The existing Access verified owner check, independent publisher token, separately approved source rights reference, 120-ticket verification, source age/provenance checks and model/odds separation all remain.
4. No Cron, provider HTTP fetch, public access, broader participant scope, paid plan or automatic betting is activated by these files. Staged owner-only `/full-odds.html` is not a completed live data experiment.

## Illustrative 300-race budget, without inventing external quotes

For N=300 races, 60 minutes of T-60 minute quote updates, 60-second intervals:
- Upstream HTTP GET budget: N × 60 = **18,000/day**, **if** source allows one page/race/min and all races actually run for the entire window. This is a scenario, not an approved provider quota.
- Latest D1 snapshots: 18,000 updates × conservatively THREE rows written per update (indexed `odds_latest` + one persistent budget-ledger write) = **54,000 D1 row writes/day**. Actual D1 analytics govern.
- With 30 viewers each checking once/minute for 10 hours: 18,000 viewer Worker requests. Combined with 18,000 ingestion requests = **36,000 Worker requests/day** before other apps, job orchestration, retries and extra APIs.
- With 100 viewers in that scenario: 60,000 viewer API requests +18,000 ingestion = **78,000 Workers requests/day**. This exceeds the **60,000 target** before accounting for other projects, even though it is beneath the official absolute 100,000.
- The self-imposed 60%-quota writes target is 60,000/day. At 54,000 assumed RACE-AI writes, only ~6,000 headroom remains for all other database updates and differences. **Do not declare all-300 T-60 free feasible until real usage supports it**.

## Pilot acceptance and scaling gate

The first test is **one real, properly usable 120-combination BOATRACE source**, 60-second update. The one-race pilot hard-stop cap allows no more than 120 accepted private ingest attempts per UTC day once manually enabled. The ingestion process must not run if the independent rights/rate/provider permission is unavailable.

Before expanding to all four sports, collect evidence of:
- Source's actual per-minute availability, lawful analysis/retention/display scope, 403/429/backoff, all valid 3T combos and provider-side update timestamps;
- Actual Worker requests, CPU and D1 `rows_read`, `rows_written`, storage bytes, 1-race comparison hashes and owner-only iPhone 60-second receipt times;
- Other Cloudflare projects' **verified** same-day quota consumption. Missing information means HOLD, not automatic source polling;
- Independent T-10 user-viewable frozen prediction receipt and official result matching (not impacted by the odds data).

**Product features stay in the GOAL even when free quotas cannot cover them.** For a measured shortage, prefer (i) static-site delivery for unchanged HTML/CSS/JS, (ii) upstream event/batch odds or conditional GET (subject to source authorization), (iii) store only latest per-race bundle not per-ticket rows, (iv) dedupe truly unchanged odds with source timestamps retained and (v) throttle/declare missing source snapshots rather than fabricate real-time data. The tradeoff between 100% of races updated every minute and strict 0 JPY requires measured provider/traffic limits. DO NOT quietly reduce the formal national-all-races completion criteria.
