# BOAT six-way A/B/C: source-authenticated readback and measured blockers
Recorded: 2026-11-09 JST. Code review ONLY, not a model promotion.

## Existing GitHub Actions production evidence, inspected in this session

Workflow run: https://github.com/haji84/RACE-AI/actions/runs/42531855305

- Artifact 13638085641 (boat-production-readback-status): JSON
  SHA256 3152ca9595208b612b3aa9ed8d716cf6ba20005559d9e6de31c1e42da9b8bfd8,
  14 admitted PRODUCTION readback race pairs, original bytes verified true,
  production schema readback verified true, but
  accuracy_improvement_proven=false,
  independent_pre_cutoff_receipt_verified=false,
  external_receipts_rechecked_live=false.
  These are PRE-EXISTING pairwise research forecasts, NOT the new six-way
  or grade-bearing A/B/C model. Reusing the result count cannot establish
  that a new model predicted those already decided races.
- Artifact 13638255176 (official-all-racers): summary JSON SHA256
  9c7ced99247a3c764d357ff839825fe97ed08c967edac2744da91e4bc096d6f6,
  official term 2026-2 ONLY, 1,643 recorded racers,
  history_starts=0, history_racers=0,
  current_active_registry_complete=false,
  formal_backtest_eligible=false,
  durable_encrypted_storage_verified=false.
  The independent summary does NOT include 2027-1 announced grade records or
  any historical K starts needed to test actual return-gap statements.
- This inspection was read-only via the existing GitHub connection; no fresh
  BOAT official provider GET or token/key operation was performed.
  Neither count-only artifact exposes the raw grade records or any
  complete frozen 120-way + 6-way tactical + qualifying snapshot.

## Implemented research path

- Existing `race_ai/boat_six_way_probability_overlay.cjs` calculates all
  ordered 120 3T probabilities, with distinct registered BOAT/frame vs
  actual entry COURSE, no hidden current-source GET.
- Existing `race_ai/boat_grade_transition_research.cjs` separates B1->next
  A1/A2 announcement, previous A-class B1/B2, and observed start gaps.
- New `race_ai/boat_six_way_matched_ablation.cjs` performs same-cohort
  A=frozen prior vs B=6-way tactic interaction vs C=B+grade learned
  adjustment, time-ordered strict holdout, 8-ticket simulated betting
  stakes/refunds, Top8, log loss, Brier120, high-payout (>=10,000 yen per
  100-yen ticket) capture and hypothetical ROI. Missing results or
  external receipts remain unaccepted.
- New `race_ai/boat_six_way_real_readiness.py` scans already-decrypted
  genuine saved views for pre-cutoff 120 vectors, formally settled results,
  pre-cutoff tactical and grade context. It only outputs count-only HOLD
  reasons, never private race IDs or runner secrets.
- `scripts/racer_intraday_refresh.py --stage-existing-pdca` adds this
  count-only field from the existing authenticated source-free bridge
  without altering source fetch, AES original, model weights, scheduled
  workflow or original receipt.
- The new `tests/boat_six_way_matched_ablation.test.cjs` uses **synthetic**
  75 cases, train60/holdout15, no lookahead and three-variant comparison.
  It cannot prove real source performance, calibration or grade improvement.

## Hard acceptance gate

The above stored evidence is NOT sufficient for any officially
authenticated grade/tactical/qualifying real-race 3-way comparison.
Must independently restore and join, in the existing Actions-only
authorized key boundary:
1. Entire genuine P1 original probability vector and signed persisted time,
   code SHA, registered boat IDs and prior cutoff;
2. The actually available pre-cutoff method histories, tilt, slow/dash
   kado/uke and event-specific ranking/qualifying board;
3. Current/next/former official grade terms proven available by as-of,
   including native K starts for observational gaps;
4. Independently authenticated official final 3T outcome, payout and refund
   revision with unique race identity.
Then train on distinct older races and freeze BEFORE later-race inputs.
Use the same held-out races across A/B/C; only count fully eligible entries.
Finally, prospectively compare same future frozen inputs, record missing
coverage and original SHA, and DO NOT promote weaker or unverified features.

Do not invent old forecasts, fabricate missing grade or course attributes,
reset manual source issue/capsule/UNKNOWN24/4xx/429 bounds, introduce a
provider GET, access a user key outside Actions, or overwrite live P0/P1.
