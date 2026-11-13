# BOAT 2026-11-12: owner-authorized formal 142-race P0 audit

Verification date: 2026-11-13 (JST). This is a **count-only, retrospective owner-authorized scoring policy** applied to the AES-authenticated original saved 2026-11-12 race cohort. It is not evidence that the originally encrypted historical display labels have been overwritten, that the public Pages site has updated, or that any bets were placed.

## Exact verified production evidence

- Original immutable source: 142 saved BOAT races and 284 P0 forecasts, two original pairwise models.
- Historical native source-only scorer: 132 formally classified, 10 legacy SP cutoff-reference HOLD, no genuinely missing race results, 264 of 284 original model forecasts evaluated.
- Owner-authorized retrospective scoring: 10 previously reference-only races admitted **only** after matching official SP result SHA and latest receipt, actual published settle/body identity, trifecta winners/payouts, and frozen forecasts saved strictly before both original and SP-source deadlines.
- Independently re-read from encrypted Git by a GitHub Actions runner: all 142 of 142 races and all 284 of 284 forecasts evaluated. Original P0/source bytes unchanged. No racing-provider GET.
- Formal model outcomes from the original independently tested settlement engine (TOP8):
  - `boat-observed-pairwise-factor-v1`: 26 hits, 116 misses, 142 evaluated. 18.31% hit rate.
  - `boat-observed-pairwise-start-v1`: 25 hits, 117 misses, 142 evaluated. 17.61% hit rate.
  - Each model gained 2 hits and 8 misses from the ten formerly held races.
- Void/full-refund outcomes in this 142-race two-model count: 0; individual start incidents were not enumerated and **must not** be inferred from this aggregate.
- All originally held reference results had RAW_OFFICIAL_SP_SAME_ROSTER_SAVED_BEFORE_BOTH basis. Nine deadlines differed by up to 60 seconds, one by more than 60 seconds. Every one had a matched official SP receipt, winning combination/payout evidence, and a forecast timestamp before both deadlines.
- The original result/prediction sources remain AES-protected and historical `cutoff_reference` markers are preserved for traceability. The new formal labels belong to the independently scored owner-authorized copy. Public site display requires separate integration; do not infer that it already reflects the new policy.

## Proof links

- Production action: https://github.com/haji84/RACE-AI/actions/runs/43339230921
- Count-only artifact: https://github.com/haji84/RACE-AI/actions/runs/43339230921/artifacts/13998397892
- Merged code PR: https://github.com/haji84/RACE-AI/pull/253
- Production scoring commit: https://github.com/haji84/RACE-AI/commit/32ce6d64ff1f149de20e446efa570ff7380ab452
- Baseline 132+10 reference audit: https://github.com/haji84/RACE-AI/actions/runs/43337556705

## Interpretation boundaries

"Formal" here means eligible in the explicitly owner-approved historical assessment of authenticated results after stricter time reconciliation, not the older default scorer's unchanged baseline policy and not a purchase/financial return record. Existing model P0 forecasts and saved source bytes were never rewritten. Historical source receipts and aggregate scores alone cannot prove how many racers committed F/L violations or were in accidents. Exact individual incident inspection needs private, source-attested receipts and should not be guessed or logged in the public repository.
