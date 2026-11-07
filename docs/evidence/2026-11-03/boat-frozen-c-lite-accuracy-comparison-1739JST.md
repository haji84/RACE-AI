# Frozen A/B/C-lite accuracy comparison: 2026-11-03 17:39 JST

## Scope and actual change

Owner instruction: improve forecast accuracy while continuing verification. This is an additive comparison of the existing C-lite challenger, not a new prediction engine or a proven improvement claim. All work stays on existing Draft PR #71.

A/B are fixed untrained models. C-lite (`boat-local-start-course-shadow-v0.1-UNTRAINED`) already used the same pre-cutoff official inputs plus local win rate, average ST and exhibition ST, but was not included in the nationwide result workflow's scoring. `race_ai/boat_shadow_result_audit.py` now validates and scores that already-frozen C-lite alongside unchanged A/B. The existing result workflow calls it after earliest-receipt exclusions. No coefficients, old original, original index, model identity, or past ranking were changed.

The comparison validates internal SHA seals, same race and source snapshot, external receipt chronology, the full 120-ticket distribution and exact Top8. It preserves missing predictions, pending results, refund/special outcomes, abnormal finishes and repeat-receipt exclusions as explicit states. Miss diagnostics are observable ticket-coverage facts, not claims about causal race dynamics. No extra official GET is needed for the added C-lite calculation.

## Execution evidence

- New two-race official audit: https://github.com/haji84/RACE-AI/actions/runs/41603265809, completed/success. Four official GET. Result artifact 13214644530, ZIP SHA256 `dd17b49d531f9acf6f1294b3c464049364dc6514971c0154068419c901152785`.
- Additive A/B/C verification revision: https://github.com/haji84/RACE-AI/actions/runs/41604866960, completed/success, exact execution commit `458b00ac2500c1e949c55a4b84496cb8bf1455af`. Two original batches, ten official GET total. This is five comparisons, NOT five new results or forecasts.
- Result artifact 13216400563, server-created 2026-11-03T08:39:30Z, ZIP SHA256 `1c3a5e242dcb6e7df4c80d413a524b3f39cae3164bf4dfd7bf90610b786f46fc`.
- Result artifact 13216730231, server-created 2026-11-03T08:39:45Z, ZIP SHA256 `d59a6cb0f07661dd5874f7f1775775df42794570baa2a723dafe0f9ddb67a05b`.
- Both result ZIPs were downloaded, their actual bytes matched GitHub artifact digests, and an independent local replay of the frozen originals exactly matched all cloud A/B/C comparison output fields.
- Fifteen new synthetic contract tests passed locally; the existing workflow also ran the new test module with its existing integrity tests. These tests prove contracts, not predictive superiority. No independent human code review is claimed.

Original archives reread unchanged:

| Original artifact | GitHub server saved at | ZIP SHA256 | Internal JSON SHA256 |
|---|---|---|---|
| 13210132613 | 2026-11-03T06:38:44Z (15:38:44 JST) | b8edc1e7980cf85ba467e48757be21bf84888dc721c2036a3d1691f0789cd383 | 4dab5d42de1ce8af860b9700722f935d5e15f12bbd2393735133e6f83a50cc1e |
| 13211344716 | 2026-11-03T07:16:40Z (16:16:40 JST) | 03be805b2da3cf96e142d98e41bf25a23d5437925838a64a068e8a13bc09b99f | c3d7f85be4e548061db22c691692694c08735994c84f092e4f86a7b21c2a5452 |

## Same five-race comparison

| Race ID | Official trifecta | Payout per 100 yen | A winning rank | B winning rank | C-lite winning rank | Official result new this cycle |
|---|---|---:|---:|---:|---:|---|
| 20261103-04-11 | 5-1-4 | 4990 | 10 | 9 | 8 | No |
| 20261103-01-02 | 1-2-6 | 8770 | 103 | 79 | 101 | No |
| 20261103-15-02 | 1-2-3 | 1090 | 54 | 10 | 13 | No |
| 20261103-24-03 | 1-5-4 | 2390 | 6 | 8 | 7 | Yes |
| 20261103-22-12 | 5-6-1 | 16510 | 18 | 55 | 78 | Yes |

All five rows passed the existing normal, settled six-finisher checks. The last two are the only new official results in this cycle. Prior three results must not be added again to cumulative result counts. C-lite comparison is newly recorded for all five. Full private predictions and raw source HTML are not reproduced here.

| Metric on these same five selected races | A | B | C-lite |
|---|---:|---:|---:|
| Hit@1 | 0/5 | 0/5 | 0/5 |
| Hit@8 | 1/5 | 1/5 | 2/5 |
| Hypothetical stake, 8 tickets x 100 yen each race | 4000 | 4000 | 4000 |
| Hypothetical payout | 2390 | 2390 | 7380 |
| Hypothetical ROI | 59.75% | 59.75% | 184.50% |
| Mean multiclass Brier | 0.9886310793 | 0.9868928184 | 0.9869118296 |
| Mean log loss | 4.6419013122 | 4.5322614570 | 4.5731423921 |
| Actual >=10000-yen outcomes missed | 1/1 | 1/1 | 1/1 |

C-lite recovers the Heiwajima11R Top8 result, but worsens winning rank on Kiryu2R, Marugame2R and Fukuoka12R versus B. Its mean Brier and log loss are also worse than B here. Therefore this sample does NOT establish superiority or justify promotion. Model scores are uncalibrated. Reliable calibration estimates and all-national Hit@8 remain null.

## Improvement decisions and hypotheses

1. Keep A/B/C-lite versions fixed for forward comparisons; do not tune their old rankings. Evaluate C-lite over all eligible frozen comparisons, not only its wins. Existing future one-shot result audits now emit the challenger comparison and coverage diagnostics.
2. Kiryu2R missed the actual winner in the first-place slot and the actual third-place boat in the third-place slot in all three Top8 sets. A claim that all misses are merely third-place selection errors is unsupported. Investigate winner selection separately from ordering within a correct trio.
3. Heiwajima11R B and Marugame2R B/C included the correct three boats in a different order. Position-specific ranking is an improvement hypothesis, not a demonstrated cause or an implemented new model in this cycle.
4. Fukuoka12R shows that adding course and start/local features can move the correct outer-boat result down. A future ablation/interaction candidate should be separately preregistered before unused races and use only verified pre-race facts. Do not invent actual entry-course history or racer attributes; absent K/history remains missing.
5. Retain the minimum evidence targets (100+ pairs, 5+ days, 10+ venue-day blocks) and perform appropriate validation before any superiority decision. A single additional hit or a five-race ROI is insufficient.

## Completion boundaries

New official results: 2. Previously known results rechecked: 3. New frozen C-lite comparisons: 5. New forecasts: 0. No new training, coefficient selection, C tactical history acquisition or automatic promotion occurred. The two complete recent frozen batches were used; this is SELECTED_RACES, not a complete nationwide denominator or a prespecified complete efficacy cohort.

No main integration, new PR, deployment, Vercel, added paid service, permission change, wager, old unresolved POST, or Drive-backup success is claimed. Cloudflare continuous nationwide operation remains unproven. This change connects a genuinely pre-cutoff existing challenger to actual outcome validation; it does not itself guarantee higher future accuracy.
