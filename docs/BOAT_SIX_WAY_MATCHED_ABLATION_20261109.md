# BOAT A/B/C six-way tactical + grade comparison (research only)

Goal: Reuse the existing immutable P1 120-outcome baseline. **No new model family.**
A = saved baseline as-is.
B = 44 tactical interaction features (1-course defense, 2-course nigashi,
3–6-course sashi/makuri/makurizashi including 5/6, tilt, fronting,
actual formation kado/uke and official event-qualifying ranks).
C = B plus 10 data-derived grade-history indicators, with **learned**
coefficients from earlier races, never a fixed A-grade bonus.

Implementation: `race_ai/boat_six_way_matched_ablation.cjs`
Synthetic tests: `tests/boat_six_way_matched_ablation.test.cjs`
Existing CI entrypoint: `tests/test_boat_six_way_node_contract.py`

Each case must have:
- Exactly one already persisted genuine P1 original with 120 positive,
  normalized probabilities before its race cutoff, independent SHA and time;
- All six correctly matched registered BOAT/FRAME to observed, as-of P1
  actual entry COURSE (not the post-race official entry as hindsight);
- Full source-attested up-to-cutoff tactical data: real exhibition tilt,
  actual venue tilt rules effective on race day, movement/4:2/3:3/etc
  slow/dash formation, past method counts, official event-qualified board;
- Complete grade rows: current application period, upcoming announced
  versus independently confirmed status, former A evidence, date of each
  as-of source capture, and retained actual starts. A missing next-grade
  item is NOT a statement that the racer will remain in B; it is HOLD.
- Already independently verified official settled 3T result with winner,
  source SHA, confirmation/capture clock, precise payout per 100 JPY
  and refunded boats. Void/unknown/ties/revised or unmatched results HOLD
  unless an explicit validated separate adapter implements them.

The source-free research code reads provided snapshots only; it **does not**
authenticate a claim just because its row contains a SHA256 or a boolean.
Owner-only independent AES readback, source/rights verification and original
freeze receipts are separate acceptance requirements.

A/B/C must be compared on exactly the SAME untouched later-race holdout.
Training result capture times must precede the first holdout forecast.
No future grade publication may enter a historical forecast.
No 3-way leakage due to race dates, roster, or model weight version.
Frozen parameters are research-only. True improvement needs a subsequent
out-of-sample future race with independent source confirmation, not
retrospective or synthetic optimization.

Report Top8, multinomial log loss, Brier120, high-payout capture (100-JPY
payout >= 10,000), and net/ROI based on a purely hypothetical 8x100-yen
allocation. Refund tickets return their original 100 yen. If required payout
or refund state is unavailable, money and high-payout metrics are null.
This NEVER reports actual bets (actual stakes/purchases are unconfirmed).
Probability calibration and real ROI improvement are NOT claimed merely by
running the code.

Current status:
- Test: 75 synthetic race cases, chronological 60 train / 15 holdout,
  A/B/C all evaluated from a single source set and source-free engine;
  no validated official observed series yet.
- Owner-key native source-result/grade inputs still require independent
  authentication in existing Actions. DO NOT cause extra source GET, bypass
  old UNKNOWN/4xx/429 caps, change the current native issuer/capsule boundary,
  or rewrite prior P0/P1.
- No production model promotion, main merge, workflow/task/cron creation or bets.

## A/B is not blocked by missing next-grade evidence

`compareAB(records, options)` uses just the original frozen P1 A and six-way
B feature inputs. It refuses to fabricate zero missing tactics, tilt, event
qualifying or original receipt, and does not require **any** current/next
grade data. Its frozen chronological sample is exactly the same as the
A/B/C implementation; when grade data is later authenticated, use `compare`
for all three variants. `compareAB` returns only A and B, never a synthetic
C score. This allows honest A/B research to progress without 2027-1 fan
grade archives. Synthetic tests alone are not a real improvement result.
