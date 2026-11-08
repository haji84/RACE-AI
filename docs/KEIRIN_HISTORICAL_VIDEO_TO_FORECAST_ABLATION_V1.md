# Historical 4-lap video -> future KEIRIN prediction: research uplift gate

## What is implemented
- race_ai/keirin_video_predictive_backtest.py runs a **train-only video-tactics ablation** against frozen pre-race baseline probabilities for every possible 3-trifecta combination (7 riders => 210, automatically N*(N-1)*(N-2)).
- Historical video facts: actual attack initiative, lead-taking, positional gain, and line survival for each rider. These labels become a rolling, smoothed **historical profile** only when their private full-lap visual review was completed **before the next target race pre-race snapshot**.
- The prediction inputs for target race: frozen pre-cutoff official candidate distribution, race's already known rider IDs/line groups/line roles, and profiles from **older reviewed video only**. Target video, target result, odds, payouts and future time windows NEVER enter the target prediction.
- Training fits bounded log-linear multipliers on Top-3 combinations using strictly earlier verified source pairs. Official base candidate probabilities are checked for full combination coverage, normalization, duplicate orders, immutable baseline digest, independent pre-race/source review.
- The candidate changes the baseline probability distribution; it does NOT replace existing PR71 code, frozen forecast originals, or the public output, and cannot submit wagers.

## Real footage / verified-data acceptance
1. A full uncut race recording must pass independent lap/replay/finish audit and have a SHA256-bound reviewed tactics file. The owner runtime must separately attest source usage, frozen pre-race model output, official result, and rights for video processing. A flag within an input JSON is never itself a permission grant.
2. Minimum 20 fully paired historical training races (each with a frozen pre-race 210-trifecta distribution, the official result, and independently verified full-race video tactics) and minimum 10 strictly later unseen test races. This is an initial *minimum engineering gate*, not enough by itself to claim 98% accuracy.
3. Strict chronological separation: ALL video reviews in training must be earlier than the first test race's as-of; no same-race or future video is used. Preserve completely untouched holdout test races for evaluation.
4. On heldout races measure baseline Top8 hits, new Top8 hits, paired log loss. A Top8 hit increase AND lower log loss is preliminary evidence of lift, never proof of calibration, expected ROI, commercial fitness, or high trust.
5. Probability calibration (Brier/reliability), odds recorded before sales cutoff, payout/return and confidence intervals remain separate validation gates. No improvement means research_model = REJECTED and PR71 stays unchanged.

## Real sources currently available
- 2026-11-08 Matsuyama 9R: uninterrupted WINTICKET browser WebM 626.320s, independent technical capture, private visual samples. **DEV only**, already used for algorithm inspection. Does not make up a 20-race training cohort.
- 2026-11-08 Matsuyama 1R: only 92.208s digest, not a valid whole-four-lap review.
- Historical official broadcast VOD discovery: operator YouTube archives may be available via UI, but the GitHub-hosted anonymous browser got LOGIN_REQUIRED. An access-control rejection is a stop signal. OddsPark desktop returned HTTP 403. The newly added source probe checks official mobile and venue VOD indexes only, without touching video bytes.
- Other older videos / frozen pre-cutoff source snapshots / rights attestations have NOT been verified as a complete dataset. **Measured predictive accuracy increase: NOT AVAILABLE.**

## Verification and data protection
- Video results are only labels for later predictions, never a same-race pre-race feature.
- Training and test evidence must remain private. Do not commit clips, frames, source files, derived raw vectors, model secrets or prediction originals to the public RACE-AI repository.
- Initial CI uses invented rider/source observations; its success proves contracts only, not actual race accuracy.
- Keep PR Draft until real-data rights, trained cohort, out-of-time holdout tests, and secure owner-side persistent storage are independently verified.
