# BOAT real A/B evaluation from immutable AES saved forecasts

## Outcome and strict distinction

A = the actual already saved pre-cutoff P1 120-outcome forecast.
B = a genuinely distinct pre-cutoff saved same-race 6-course tactical shadow,
not a retrospective reconstruction from the settled finish.
A/B does NOT depend on 2027-1 grade or historical A-class records.
C adds grade features only when evidence was available before race cutoff.

## Existing source-free integration

race_ai/boat_six_way_matched_ablation.cjs:
compareAB(rows, options) evaluates A against B with the SAME chronological
train and holdout cases. compare(rows, options) additionally evaluates C
only if current/upcoming/prior official grades were recorded as of forecast.
Both use a frozen A original SHA/persist timestamp and 120 tickets.
Current and previous grade are NOT automatic ability bonuses.

race_ai/boat_six_way_saved_ab_score.py:
- Existing caller authenticates an AES saved-view; scorer finds EXACTLY one
  original A and a distinct B with research variant B_SIX_COURSE_TACTICS.
- B must bind to the SHA256 digest of the full baseline A record, its own
  hashed six-way context, matching physical race, and the same cutoff.
- Each prediction must contain all 120 positive normalized orderings and
  eight distinct Top8 tickets consistent with the ordering.
- The existing _result_context checks latest formal RESULT revision; the
  existing _score_using_existing_bulk_engine checks official payout, ties,
  8 x 100 JPY simulated stake and refunded boats. No real purchases.
- No B frozen pre-cutoff = HOLD, never a zero-scored miss.
- When one final winner and no refund, compare full120 log loss/Brier120;
  otherwise mark those probability metrics unknown rather than invent.
- All output is count-only; no private race ID, predictions, original raw
  bytes, source keys, wager records or racer names escape.

scripts/racer_intraday_refresh.py source-free PDCA stage:
adds six_way_research_readiness and six_way_saved_ab_study counts from the
already AES-restored existing views. No added cron, workflow, source GET,
model family, forecast publication or original write. The existing private
encrypted state, source caps and issuer HOLD remain unchanged.

## Real source evidence inspected (NOT new B forecasts)

Github Actions 42531855305 artifact 13638085641 contains 14 actual stored
pairwise research races from existing boat-observed-pairwise models; those are
not new B_SIX_COURSE_TACTICS forecasts. Independent external pre-cutoff
receipt recheck was not demonstrated by that artifact.
Artifact 13638255176 has 2026-2 official term 1643 racer rows but
zero historical K starts, no 2027-1 grade records in that checkpoint.
Neither can establish genuine post-introduction B frozen forecasts.

## Acceptance gates

Existing source-free synthetic 75-race trial (60 old train /15 later holdout)
proves computation only, never accuracy. The Python AES fake fixture proves
the existing bulk settlement path and HOLD handling only.

Require owner-only Actions independent readback of genuinely saved
pre-cutoff A/B, actual term/source proofs, official latest RESULT and payout,
no post-race B reforecast, same physical race Top8 and simulated net/ROI,
time-ordered future comparisons, and CI green at one exact integrated SHA.

Do not reset manual official source-issuer/capsule HOLD, UNKNOWN24, 403/429,
source quotas, workflow, main, production parameters, private keys or
original saved predictions. No new provider GET or real betting.
