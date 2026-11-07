# JRA 2026-11-07 / 2026-11-08: four-stakes prospective input gate (2026-11-04 JST)

Existing Draft PR #71 only. No new model, task, workflow, permission, cloud, or public feed.

## What was checked (registration-stage, **not** official final runners)

- Tokyo 11R Nov 7 Keio Hai Nisai Stakes (turf 1400m): 10 registrants.
- Kyoto 8R Nov 7 Kyoto Jump Stakes (obstacles 3170m): 10 registrants.
- Tokyo 11R Nov 8 Copa Republica Argentina (turf 2500m): 22 registrants, 18 initially eligible.
- Kyoto 11R Nov 8 Miyako Stakes (dirt 1800m): 19 registrants, 16 initially eligible.
- Total 61 registered; 54 projected eligible. This is not a final scratch/draw count.
- Published external performance index observed for 58/61, while prior up-to-three-run finish entries were transcribed for 51 registered flat-race horses. Third-party raw factual data and candidate picks are kept in owner-side private conversation files and are **not** uploaded to the public repository.
- Do **not** treat a published index or last-three-runs podium rate as the 12 independently normalized RACE-AI model features.
- Reference-only min/max cannot extrapolate into excluded horses; previous exclusion/negative minmax values were corrected in the private audit.

## Existing four model gate

Use the existing `race_ai/four_sport_model_suite.run_suite`; research model IDs are unchanged:
- multisport-factor-interaction-v1
- multisport-scenario-ensemble-v1
- multisport-conditional-duel-v1
- multisport-race-trajectory-v1

`scripts/horse_weekend_input_gate.py` adds a read-only missing-evidence report and delegates to the original suite only after input checks; `tests/test_horse_weekend_input_gate.py` tests missing features, independent authorization, jumps exclusion, and existing-suite execution on **fictional fixtures only**. A synthetic test success is not a prediction for 2026/11/7-8.

In the original native input schema (see `race_ai/comprehensive_four_sport_models.py`), each horse requires 8 common + 4 horse-specific normalized evidentiary observations. Each race requires 5 common + 4 horse-specific environment observations, actual runner number / draw / unique ID / running style, the official cutoff time and `as_of`. Each observation needs value, evidence/source references, use-rights record, publishing and capture times, sample size, and transformation version. The source-permission callback must be independently authorized. Do not put future results, odds, popularity or payouts into model features.

## Actual status on 2026-11-04

1. Registered horse and 3-run factual intake: PARTIAL (61 names, 51 histories).
2. 12 real normalized features per actual runner: BLOCKED (not fitted/verified).
3. 9 evidentiary environmental observations: BLOCKED (not complete).
4. Independent source authorization, final horse IDs/draw, official cutoff, as-of snapshot: BLOCKED.
5. 4 existing models executed on **this weekend's real races**: ZERO.
6. Calibrated win probabilities / truthful confidence / 3-way ticket EV from current official odds: NOT AVAILABLE.

JRA says the four 2026 racecards are scheduled for public release Thursday Nov 5. General JRA FAQ says number-less runner list after 16:00 Thu and numbered card around 10:00 Fri for eligible advance-sales stakes. Check official dates and withdrawals, never assume final draw from preliminary listings. Official *start time* is not the official betting cutoff.

Kyoto Jump is special: the existing flat-race horse scoring model has no observed jumping/obstacle risk or fall/failure feature. Encoding the jump race as `surface=turf` does **not** validate it; keep it separately marked as an out-of-scope research case.

## User-facing completion rule

Only after an actual qualified, authorized data snapshot exists should the existing four models be run with the **same** input SHA and as-of. Record each original top-eight pick, scores, and SHA *before* cutoff independently. Calibrated probabilities and EV require further independent historical holdout and actually observed market odds. Never fabricate a 90% forecast confidence from an uncalibrated score.

## Public primary sources

- JRA official racecards: https://www.jra.go.jp/keiba/race/099/syutsuba.html ; https://www.jra.go.jp/keiba/race/100/syutsuba.html ; https://www.jra.go.jp/keiba/race/101/syutsuba.html ; https://www.jra.go.jp/keiba/race/102/syutsuba.html
- JRA card publication FAQ: https://www.jra.go.jp/faq/pop02/2_2.html
- Radio Nikkei registered runners: https://www.radionikkei.jp/keiba_article/news/post_38958.html ; https://www.radionikkei.jp/keiba_article/news/post_38960.html

Internal owner-only data audit produced Nov 4 is **not** in GitHub, and should not be substituted with reconstructed/guessed inputs.
