# BOAT pre-frozen A/B/C-lite 4-race comparison, 2026-11-04 04:24 JST (diagnostic only)

## Scope / priority
- Existing Draft PR #71 / Issue #67/#68; no new model, prediction, ranking, wager, PR, workflow, or coefficient changes. This is **one offline re-evaluation of four previously official-verified races**, not four new results and not a new pre-cutoff freeze.
- 2026-11-04 earliest cutoff in the independently checked **00:26:58 JST** original daily discovery was Ashiya 1R 08:35 JST, followed by Mikuni 1R 08:47 JST, with 12 venues/144 potential race slots. At 04:24 JST this was before racing/exhibition; **0 new same-day forecast receipts**, and the 00:26 discovery is not a fresh 04:24 official GET. Official day results not claimed.
- Original daily discovery: run 41663948277 / artifact 13244030784, original ZIP SHA256 `c16533f19fa6063403bbf0f04df0d37a7f26026aa6dcf605611ddf189f006bf8`. Independently re-read this existing local ZIP before the comparison; 144 slots are NOT 144 forecasts.
- Existing immutable index at the reviewed head had 26 distinct A/B race IDs from Nov 3; **no index entry was added or altered**. Earlier Heiwajima 7R original takes precedence over later frozen observation, as in the prior observation policy.

## Source archive and independent result checks
Three original ZIPs were byte-read and SHA256 checked against authenticated GitHub Actions artifact metadata and the existing frozen index. Every internal `national.json` SHA was checked. The original `paired_forecasts` A/B and `additional_official_feature_shadows` C-lite each have matching **pre-cutoff official snapshot SHA for each race**; C-lite has additional legitimately captured fields, not identical feature definitions. Each original model's ranked 120 distinct trifecta tickets was checked, including that its first eight match the originally frozen top8. Each source forecast generated time and GitHub server-created time predate cutoff. Independent result artifact `result.json` is a **separate post-cutoff event** and its original ZIP SHA was checked; previously graded outcomes were not counted as new.

| Original artifact | Original ZIP SHA256 | Frozen JSON SHA256 | Independent result artifact | Result ZIP SHA256 |
|---|---|---|---|---|
| 13220026930 (Kiryu 9R) | `f28658165f425f8f68b0091f463ca70eb14b1af6e51952d07710ee6197dc63c9` | `de4ade8a167bad6fe32e86a03b0fb3eb16c8af53a0bc9dade502289d61e1b53b` | 13221728430 (run 41617850239) | `19b87f0ca49210c791c7fa3161cf5e5f366531e0ed10d664495cbb881eaaa311` |
| 13220834629 (Kiryu 10R) | `5c24d00e07eca02ef804b441ef0ecb6f69c32b3f65395f6b55057f8cd0d65a27` | `768a5375db3de3269e35d064a5818ae2e982a1628706bbb25f842b78b2e98296` | 13226179175 (run 41628108709) | `696c04ceac03dedbd6a359a7e475d01dd8b0a2cc4c77dda32de55911ac1f4690` |
| 13204251708 (Miyajima 8R, Tokuyama 11R) | `9a875585e3e3d93f4683f3f422667e7df7526ab2c2aa700f78ef6e97f6198c5e` | `1df6a56e4b9ce62aa87da1e817d224e225e99d02c9ff9298b251d356101d0f65` | 13261970136 (run 41695227877) | `3d3fce1140d8f19ff591de6c650d8681032a253bb8f33051bc8914d1cdc1bcf0` |

## Same-race result-to-locked-rank matching

| Previously verified normal result | 3T / 100-yen payout | A winner rank | B winner rank | C-lite winner rank |
|---|---|---:|---:|---:|
| 20261103-01-09 Kiryu 9R | 1-4-3 / JPY 6,810 | 64 | 30 | 18 |
| 20261103-01-10 Kiryu 10R | 1-4-3 / JPY 1,980 | 20 | 8 | 28 |
| 20261103-17-08 Miyajima 8R | 1-2-3 / JPY 830 | 28 | 7 | 3 |
| 20261103-18-11 Tokuyama 11R | 2-1-4 / JPY 2,640 | 25 | 9 | 5 |

Existing independent result event for Heiwajima 7R 20261103-04-07 has a lane-5 abnormal fall (`落`) and observed 1-4-6 / JPY 14,710. It is **excluded** from ordinary six-finishers ROI/Hit@k. It is an observed >= JPY 10,000 payout, but **not a regular four-race cohort member**. No unverified result is labeled a win/loss.

## Counterfactual fixed-top-K evaluation on original 120-rank lists

These are **retrospective read-only slices of original pre-result saved full rankings**, not separately time-stamped/persisted pre-result 1/3/6/12 ticket-plan receipts. **Only the original top8 has the actual pre-cutoff model forecast freeze**. Do not merge the top12 diagnostic with formal prospective top12 performance.

| Research model | Hit@1 | Hit@3 | Hit@6 | Hit@8 (original frozen) | Hit@12 (unfrozen derived slice) | 8x100 yen virtual stake | 8-ticket payout | 8-ticket ROI / net |
|---|---|---|---|---|---|---:|---:|---|
| A display PL (unvalidated) | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 | 3,200 | 0 | 0% / -3,200 |
| B course/motor (untrained) | 0/4 | 0/4 | 0/4 | 2/4 | 3/4 | 3,200 | 2,810 | 87.8125% / -390 |
| C-lite local/ST (untrained) | 0/4 | 1/4 | 2/4 | 2/4 | 2/4 | 3,200 | 3,470 | 108.4375% / +270 |

- No ordinary real >= JPY 10,000 winning payout in these four normal races, hence **normal-cohort manshu capture is N/A (0 denominator)**, not 0% success. Abnormal Heiwajima observation remains separate.
- A/B/C-lite unchanged, uncalibrated research scores. No historical outcome used to change a pre-cutoff prediction. No research model promoted.
- Selected 4 common ordinary races from one calendar day are **far short of the minimum prospective gate: 100 common races, >=5 race dates, >=10 venue-day blocks**. The 4-race rate is neither national Hit@8_all nor evidence of an outperforming model.
- All 2026-11-03 other normal sold/settled races, including those without forecasts, remain part of the still unaudited full-target denominator. National forecast coverage, whole-population Hit@8_all and statistical tests are **not computed**.
- New 2026-11-04 futures: **none generated in this 04:24 run**; no exhibition yet. No official result was newly fetched or newly scored. Source permissions and rate limits were not broadened.
- No new permanent backup ZIP is needed here because no original forecast ZIP was created. No new Google Drive write/permission mutation, PR, main merge, Cloudflare deployment, Vercel usage, charges or bets.

## Independent re-derivation
A local read-only checker re-opened all three original ZIPs and three later result ZIPs, validated six archive hashes, three original JSON hashes, shared source-snapshot hashes, official result event time > cutoff, and 120 unique ranking tickets for all 12 model/race records. Derived JSON checksum SHA256 `6b4c8ecd66b337d929d24df1a62a6bbdf16f7f216b55dedec88454f4f49f97d3`; the JSON is a local diagnostic attachment, **not a new immutable GitHub forecast source**. Aggregation counts every normal race once per model and treats the full-result observations as previously seen events.
