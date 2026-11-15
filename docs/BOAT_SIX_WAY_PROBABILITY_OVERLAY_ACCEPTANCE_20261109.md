# RACE-AI | BOAT six-way 120-outcome tactical overlay (research-only)

## Implemented in detached code, not live PR #71

The supplied stage P1 original baseline is a frozen complete 120-ticket
probability vector. The experimental engine applies a conditional multinomial
logit correction to those **same 120 ordered outcomes**. All outcomes are
renormalized to a total probability of 1 and Top8 is derived from the same
distribution. If coefficients are absent/zero, the original probabilities are
unchanged. Original saved P0/P1, weights and receipts are NEVER rewritten.

Relevant source files:
- race_ai/boat_six_course_tactical_features.py: pre-as-of course and style history
- race_ai/boat_dynamic_tactical_context.py: current P1 tilt, dynamic formation,
  inside/outside entry and event qualifying standings research inputs
- race_ai/boat_six_way_probability_overlay.cjs: 44-factor overlay,
  strict source-free validation, 120 normalized values, independent trainer and
  strictly chronological race-level holdout
- tests/boat_six_way_probability_overlay.test.cjs: synthetic contract tests

## Learning input and source-boundaries

record = {stage:"P1", context: six_way_research_context(...),
          cutoff_at: ISO time with zone,
          baseline: {race_id, as_of, full_120:[{ticket,score} × 120]}}
historical result entry =
  {input:record, result_ticket:"1-2-3", result_captured_at: ISO,
   result_source_sha256: previously authenticated official result sha256}

Upstream is responsible for independent authentication of context and source
bytes inside the existing Actions secret/vault boundary; a claimed SHA or
boolean is insufficient. All 6 identities, 20 style rate channels, exhibition
tilts, 4:2/3:3/etc kado and kado-uke, preclose actual observed/claimed
course and event-specific official score/rank cutline must be present.
Missing/unknown values raise an explicit HOLD; no zeros or synthetic values
stand in. Last 10/current meeting data and historical course-specific
sashi/makuri/makurizashi for 5 & 6 remain distinct.

The 44 factor channels include distinct fifth/sixth makuri and
makurizashi, first-course historical winner-method loss descriptions,
second-course nigashi, high tilt by actual outer course, current formation
kado-uke, inward/outward prior success and current published ranking rates.
This is an experimentally fitted statistical association, NOT causal proof
that a specific racer actually blocked, attacked or altered the outcome.

Official 3T tickets denote BOAT/FRAME numbers, not actual entry courses.
For example, if BOAT 6 enters actual course 1, that course's style features
apply to BOAT 6, while the ticket remains 6-... . Explicit frame-to-course
bijection is mandatory, including fronting/displacement.
The first-course win share is P(the winner entered course 1), NOT
P(winning method == nige). The latter is null until a separately verified,
conditionally modeled winner-method result is available.

The fit operation learns coefficients solely from earlier races, freezing
them before a chronological later-date holdout. A strict checkpoint prevents
training RESULT timestamps from reaching the first holdout input as_of.
Individual races are unique and the result capture clock is after original
cutoff. Stored frozen coefficients cannot be applied to a race in their
training IDs or to a race before the model trained_through timestamp.
A real subsequent future cohort is STILL necessary for improvement claims.

### Checks performed to date
- V8 parsed exact engine bytes from GitHub blob.
- Synthetic test harness: 15 checks including 120 distinct tickets/sum 100%,
  missing-course and qualifying HOLDs, 5th/6th high-tilt effects, moving kado
  3:3 to 4:2, source clock, no original overwrite, same-race training leakage,
  52 older training cases / 18 synthetic holdout cases, frozen future predict.
- Synthetic holdout is **not** evidence of authentic performance improvement,
  real fitted input, or correct true official payout/ROI.
- No current production CI was launched by this detached code.

### Remaining gates before use
1. Fresh branch HEAD and source issuer fixed-target HOLD check; preserve existing
   BOAT predictions, worker concurrency, UNKNOWN24 and 4xx/429 boundaries.
2. Review and safe CAS integration with parallel owner code. Run full CI at
   exact new SHA and independent tests.
3. In existing Actions-only secret context, independent source proof of real
   P1 before-cutoff 120 predictions, historical B/K settlement, every tilt and
   entry record, event qualifying standings and revisions, and encrypted
   append/readback; never use unknown values as zero.
4. Fit baseline vs overlay on earlier races, time-frozen holdout and then
   same-input prospective race A/B; evaluate log loss, Brier120, Top8,
   high-payout capture, official-100-yen ROI when independently settled,
   and date/event/racer leakage. Reject gains observed only in synthetic data.
5. Read-only existing dashboard can show the experimental vector with explicit
   source and calibration statuses. No silent model promotion or changes to
   official predictions/bets/main/workflows.

No new model family, scheduled task, workflow, paid service, provider GET,
source-cap reset, user secret, permissions, deployment, or real wager.
