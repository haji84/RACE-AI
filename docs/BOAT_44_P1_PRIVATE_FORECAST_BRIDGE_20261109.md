# BOAT 44-factor P1 bridge to existing 120-ticket overlay (2026-11-09)

Scope: source-free research-only draft against PR #71. No new prediction family,
fitted coefficients, provider GET, cron, protected-main change, source quota
reset, plaintext originals, public raw forecasts, paid service or bet.

## Wired in this draft

- race_ai/boat_44_p1_input_bridge.py: assemble_p1 takes six registration IDs
  from the official program, admitted pre-as-of historical K results with
  winner methods and actual entries, today's attested exhibition, current
  venue tilt rules, event-specific provisional points, and the EXISTING
  full-120-ticket baseline prediction from the identical race/as-of.
- Reuses unchanged analyze_racer, entry_response_profile, matchup_features,
  p1_tilt_entry_context, qualifying_standings and six_way_research_context.
  Winner method never proves a particular loser's blocking cause. Dynamic
  kado/kado-uke are derived from actual source-backed slow-count.
- Missing or structurally unobserved observations stay None, never invented
  0%. Missing authentic standings, incomplete historical exposures, missing
  real tilt rules, mismatched six racers or source denials cause HOLD.
- scripts/boat_44_p1_private_predict.cjs executes the EXISTING
  race_ai/boat_six_way_probability_overlay.cjs with a separately frozen
  chronological 44-factor coefficient artifact, returning original Top8,
  candidate Top8 and 120 uncalibrated research scores. No trained artifact
  means HOLD_NO_FROZEN_TACTICAL_MODEL. Output only to private create-only
  0600 file, never raw stdout, never public GitHub.
- Prospective mode requires execution after source as-of but before the
  actual cutoff time; replays have distinct labels and cannot serve as
  prospective freeze evidence. No public prediction storage is added.
- New synthetic tests check missingness, source admission rejection, after
  as-of leakage, exact IDs, candidate overlay output, 120-way sum and HOLD.

## Not established

Actual source restoration, independent provenance readback and complete
per-race feature acquisition for 2026-11-09's 132 events: NOT VERIFIED.
Prediction from a real fitted 44-factor research artifact for any of those
events: NOT VERIFIED. Previous conversation-wide 132 selections were simple
heuristics, and cannot be relabeled as model originals.

Existing official B/K/term historical materials are privately encrypted,
so must be verified in owner-only GitHub Actions. Source names, hashes, source
permission and as-of clocks must be authenticated, not asserted from a
caller-supplied boolean. Data unavailable in time must remain unknown.

The existing overlay fits only with at least 50 matched historic cases and
time-ordered holdout (over 40 training, over 10 holdout). The seven known
earlier real paired pilot cases are not proof of the 44-factor fit or
predictive gain. Synthetic fixture coefficient values are not real models.

## Private operator sequence

1. Restore existing encrypted owner history and frozen models through
   verified GitHub-only state readback without resetting it.
2. Verify future race six IDs and cutoff, source version, official past K,
   pre-close exhibition/entry/tilt, officially current venue-specific rule,
   meeting-specific qualifier positions, and existing same-as-of baseline
   full-120 model predictions. Independently enforce source rights.
3. Pass these bytes to assemble_p1. Keep missingness and HOLD reasons.
   Do not use after-cutoff results in prediction features.
4. Only with an authenticated historical fitted frozen research artifact,
   privately invoke:
   node scripts/boat_44_p1_private_predict.cjs
   /private/boat44-input.json /private/boat44-output.json
   Input schema: RACE_AI_BOAT_44_P1_PRIVATE_BATCH_V1;
   mode: prospective; frozen_44_model: existing overlay artifact;
   races: bridge output rows.
5. Use existing AES-GCM store and independent receipt readback for freeze,
   then existing result checker for returns, refunds, Hit@8, Log loss, Brier,
   high payouts, and comparative ROI. Never call synthetic tests PDCA.
6. Promote nothing automatically; retain protected main review/CI boundary.
