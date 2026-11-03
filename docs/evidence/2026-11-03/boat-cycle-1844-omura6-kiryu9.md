# BOAT single-cycle source audit and future freeze, 2026-11-03 18:44 JST

Scope: one owner-approved cycle, same existing Draft PR #71. No new PR, no automatic wager, no Vercel, no model auto-promotion. Selected observed races, not an all-national forecast or efficacy denominator.

## Official discovery and yesterday
- Today's official nationwide schedule was fetched. The bounded existing collector confirmed 13 active venues, 156 race slots, 19 official GET, but successfully generated only ONE new three-model race forecast. Slots discovered are NOT forecasts frozen.
- Official November 2 schedule is readable, but no independent per-race original predictions from that date were authenticated in this cycle; do not score yesterday retrospectively or invent a national denominator.

## New official result: Omura 6R
- Race ID: `20261103-24-06`. Official scheduled close: `2026-11-03T17:48:00+09:00`.
- Original GitHub Actions run `41604737335`, artifact `13216650196`, server-created `2026-11-03T08:38:23Z` (17:38:23 JST), ZIP SHA256 `2404d075de551bd4595d002366f19b65c407e82ecacb047637d36b6b12fa5f49`, inner national.json SHA256 `3e73564c18301938be70b985b8e6413aa08e9d1134ec192769224031c9b4b848`. Original bytes reread unchanged.
- New independent result run `41613445619`, artifact `13219379304`, result ZIP SHA256 `21ac8b7881d720ee7cc0eb48bb42fc99f51b3339d3297818ff42525112433ee8` (server `2026-11-03T09:44:38Z`). Two official GET; the validated race had all six finishers with no refund/special finish.
- Official individual result: `1-3-5`, 100-yen trifecta payout JPY 550, no man-shu. Official source: https://www.boatrace.jp/owpc/pc/race/raceresult?hd=20261103&jcd=24&rno=6
- Against the SAME preclose fixed A/B/C-lite source:
  - A `boat-display-rating-PL-reference-v1-UNVALIDATED`: winner rank 16, Hit@1=0, Hit@8=0, Brier 0.9832198773, log loss 4.3216142914, eight-ticket virtual payout JPY 0.
  - B `boat-course-motor-shadow-v0.1-UNTRAINED`: winner rank 12, Hit@1=0, Hit@8=0, Brier 0.9792114416, log loss 4.1518733263, virtual payout JPY 0.
  - C-lite `boat-local-start-course-shadow-v0.1-UNTRAINED`: winner rank 7, Hit@1=0, Hit@8=1, Brier 0.9727977435, log loss 3.9525623645, virtual payout JPY 550.
  - Virtual stake is JPY 800 per model; C-lite virtual ROI this SINGLE race 68.75%. This is not actual betting, a statistically valid improvement, or a calibrated hit probability.
- Observed coverage difference: the winning third boat was absent from A/B's third-slot Top8, while C-lite included the winning `1-3-5` order at rank 7. This is a descriptive miss classification, not proof that its added local/ST features caused the recovery. No coefficients changed.

## New forward forecast: Kiryu 9R
- Race ID `20261103-01-09`, verified scheduled cutoff `2026-11-03T18:55:00+09:00`.
- Original GitHub Actions run `41613473219`, artifact `13220026930`; GitHub server-created `2026-11-03T09:44:46Z` (18:44:46 JST), 614 seconds BEFORE scheduled cutoff.
- Raw original ZIP SHA256 `f28658165f425f8f68b0091f463ca70eb14b1af6e51952d07710ee6197dc63c9`; inside national.json SHA256 `de4ade8a167bad6fe32e86a03b0fb3eb16c8af53a0bc9dade502289d61e1b53b`; A/B bundle SHA256 `ea04b8a3d9accb1306553d7ed7024e1555a494ddf8282ee8d9b3539233c172fa`. Raw ZIP and internal bytes reread and hashes matched GitHub.
- Six matching official racers and published exhibition inputs generated A/B and distinct C-lite, Top8 each. Models are untrained/uncalibrated. Actual result not used; official result remains PENDING at this audit time. No prospective winner/rate is claimed.
- Canonical index updated append-only 22 -> 23 unique race IDs; earlier originals unchanged, no second freeze for any existing ID. Earlier Heiwajima 7R earliest-receipt rule remains enforced.

## Safeguards and limits
- Google Drive destination metadata rechecked: `shared=false`, one owner permission. The new ZIP was NOT backed up there: connector upload rejected the file-reference type. Stop safely; no duplicate, overwrite, sharing change, or backup-success claim. Public GitHub does not include owner Drive location or raw forecast tickets.
- C tactical past K/venue histories NOT authenticated, so no tactical shadow or guessed racer attributes; C-lite remains separately identified. Pre-close 100x odds are not an actual confirmed 10,000-yen payout. No man-shu hit on the new result.
- Same one-shot Actions are not always-on nationwide execution. National Hit@8_all, Brier calibration over complete target population, and A/B/C statistically significant advantage remain unavailable. Cloudflare production Cron/D1 continuous operation remains unproven.
- Status: new official results = 1, new unique preclose A/B+C-lite forecasts = 1, ordinary results scored = 1; this single-cycle result is not cumulatively added twice. No result or any model estimate was back-written to original frozen predictions.
