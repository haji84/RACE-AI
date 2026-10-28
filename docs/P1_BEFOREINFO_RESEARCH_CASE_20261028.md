# Participant-bound exhibition input for a research comparison

This slice adds a pure conversion from an already supplied B racelist and parsed
beforeinfo snapshot into the existing display model's P1 research input. It
does not acquire data, run a model, create a receipt, or change a saved forecast.
The prior 132-race cohort has no retained pre-cutoff beforeinfo and cannot be
backfilled by this work.

## Reuse and output

Reuse `boat_existing_asset_integration.build_readiness` and its existing
`boat_preview_weather_evidence` normalizer for race, cutoff, lane/registration,
display and ST validation. Leave both gates and all model coefficients unchanged.
The separate pure module is `boat_beforeinfo_research_case.py`.

`project_beforeinfo_display_case(racelist, preview_snapshot, *, as_of,
input_pins, source_rights_ref)` returns a detached envelope. Its manifest binds
the canonical hashes of both supplied objects, exact race/date/cutoff, original
decision and capture times, source URLs and hashes, explicit publication values
(including null), declared rights reference, and all six lane/registration pairs.
The source manifest digest binds supplied bytes; it does not authenticate a
provider or prove the original source rights or receipt.

With six valid display times, `case` has the existing replay input shape:
`case_id`, `stage=P1`, `legacy.boats`, and `source_manifest_sha256`. The six sorted
boats contain only `lane`, `national_win_rate`, and `display_time_s`. The existing
replay caller can consume this case without changing its roster or constants.
Only the uniform, rating and display numeric branches have the supplied fields.
Both name-bound aliases require complete original timings in the unchanged
runner, so they remain blocked, as do the original-timing and pairwise branches.
An alias would never be a verified name-binding wrapper or a separate algorithm.

No pairwise snapshot, ST, weather, course, history, original lap/turn/straight
timings, probabilities, tickets, odds or results enter the case. The live
exhibition wrapper's durable-receipt requirements and the permissioned four-model
case profiles remain separate and unchanged.

## Input checks and missingness

- Require six unique integer lanes and ASCII registration identities, exact
  race/date/cutoff agreement, and canonical input hashes. Join by lane plus
  registration, never by name, prefix, or row order.
- Require the exact date-specific official B URL and race-specific beforeinfo
  URL, finite source values, source hashes, and the existing declared
  `user-confirmation-2026-10-15-official-facts` reference. This check grants no
  source or purpose permission; a real caller still owns admission.
- Require capture at or before the supplied decision, before the unchanged
  supplied cutoff. Preview capture and decision belong to the race's JST date.
  Publication, availability and save claims must not contradict their order.
  Unknown publication stays unknown; capture is not renamed publication.
- PENDING or incomplete display yields an explicit blocked result and null
  case. The projector's display range is 1 through 20 seconds. Valid lower
  values accepted by the old normalizer are explicitly outside this projector's
  range, not replaced or silently converted.
- F/L with null numeric ST does not block a display-only case; diagnostics retain
  the original F versus L distinction per lane. Contradictory
  F/L plus a numeric ST is invalid. No ST, course, sample count or weather value
  is invented to satisfy another model.
- Bound input size/depth, reject non-finite numbers and unknown fields at every
  owned structural boundary before any PENDING/incomplete early return. Reject injected odds, results, payouts,
  probabilities or strengths even when a caller recomputes the input hash.
- Preserve inputs, expose no I/O or clock callback, and execute no inference.

The output remains research-only. Forecast execution, official prediction,
formal final-test eligibility, historical freeze, verified publication/rights
and individual receipt claims are all false.

## Acceptance and limits

Meaningful fictional tests cover identity swaps, timestamp/cutoff boundaries,
F/L missingness, source/pin changes, leakage injection, input immutability and
compatibility with the unchanged static replay case contract. Independent
design and implementation review precede exact-head Windows/Linux CI.

After review, one retained historical case may be converted locally using its
own original B, baseline linkage and beforeinfo bytes. A separate fresh
conversion clock must distinguish execution now from the old decision context.
This is already-exposed research: no source refetch, result read, prediction
regeneration, old journal modification or new prospective claim. Private
source data and detailed converted values stay outside the public repository.

Full19-model execution, real future P1 freeze, unused-period validation,
four-sport real E2E, formal GitHub approval/main integration and final product
acceptance remain separate unmet conditions. Owner device/cost acceptance stays
deferred; no cloud, paid, source-rights or security setting changes are included.
