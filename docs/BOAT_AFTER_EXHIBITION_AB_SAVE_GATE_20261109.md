# BOAT post-exhibition all-race A/B handoff, 2026-11-09

## Code-only connection to the **existing** P1 AES original pipeline

The following modifies no workflow, source request allowance or production
forecast/original. It extends the existing P1 Actions owner path:

- race_ai/boat_post_exhibition_ab_handoff.py
  - Requires a 6-racer official B + beforeinfo identity, six exhibition
    times/ST/tilt, source SHA and source-captured clock.
  - Requires a **separately source-witnessed actual START EXHIBITION course
    assignment**, not an assumption that a frame/printed position number is
    a course in the race. It is only a provisional exhibition shape, never
    proof of the actual START course at the physical race.
  - Requires a current event-specific published qualifying-board snapshot,
    the current effective venue tilt rule, prior real method/entry histories,
    and a frozen TRAINED six-way research coefficient vector.
  - Requires already saved A: exact P1 120 scores and Top8, original
    physically attested pre-cutoff server timestamp and original digest.
    The prior A time is preserved and may be earlier than the later
    exhibition B as-of. It is not backdated to generate B.
  - Runs the existing 44-feature 120-ticket Node overlay without HTTP or
    inherited credentials; B must be distinct from A and generated with
    P1 current data at least 120 seconds before the official cutoff.
  - Never reopens A, changes prior model parameters, or uses results/odds
    as forecast features. Produces RESEARCH candidate, not a real bet.
- race_ai/boat_all_model_cycle.py.forecast_round:
  - Optional owner-prepared B inputs are generated/held alongside the
    existing P1 native reports in the SAME AES payload. No prepared
    inputs means unchanged P1 operation, no B inferred from scratch.
  - Missing research inputs on a given race cause an explicit independent
    HOLD, without blocking P1 A or other ready races.
- scripts/boat_all_model_cycle.py.generate/readback:
  - Existing runner reads only an optional 0600 private file at
    RUNNER_TEMP/boat-sixway-owner-prepared/cycle-N.json. Exact fields:
      schema=RACE_AI_OWNER_PREPARED_POST_EXHIBITION_AB_V1,
      run_id=actual GitHub run id,
      source_code_commit=exact checkout SHA,
      round_no=N, research_ab_inputs={official_race_id: {
      context: authoritative pre-cutoff six-way feature context,
      frozen_model: previously time-frozen fitted parameters,
      formation_evidence: independent source proof of start exhibition course
      }}.
  - The optional private file is input-hashed into the existing AES sealed
    round manifest so it cannot be added later to the same stored run.
  - Existing P1 encrypted artifact is later re-downloaded and verified
    independently for run/HEAD/bytes and GitHub physical created_at.
    Each B is counted as accepted ONLY when original generation <= actual
    independent server save < the original official cutoff. A late upload
    holds B without changing the old P1 or marking it a losing forecast.
- race_ai/boat_post_exhibition_ab_coverage.py
  - Counts ALL scheduled races from the original frozen official P0 schedule
    when available, by venue and source state, never assuming 132 if the
    upstream official schedule has another count.
  - Incomplete P1 input, captured after cutoff, absent A/B, missing
    real future feature stores remain WAIT/HOLD. No retroactive B creation.

## Why 132/132 cannot be asserted for Nov 9

By 2026-11-09 15:18 JST, many same-day cutoff times had passed. The
legitimate B record must be physically frozen BEFORE each individual cutoff.
A retrospective computation cannot be promoted to an earlier forecast.

Existing public beforeinfo collection in main has been observed to retain
pre-race values, but it explicitly reported forecast_inputs_used=false and
forecast_inputs_changed=false. Its official parser intentionally leaves
exhibition_course=None, because the HTML source position is not independent
proof of a racer taking a particular prospective course. Additionally, the
current archived full-term 2026-2 checkpoint reported 0 K history starts
and no 2027-1 official next term; that absence does not block A/B grade-free
comparison but missing historical 6-course tactics or event qualifying
features DO block the full 44-factor B. No course, score or probability is
invented to fill the gaps. Current source owner's fixed issuer/capsule
HOLD is not bypassed by code review/CI green.

New code can be shipped safely on the PR71 CODE-only branch. Actual no-human
production requires existing approved source owner to prepare real private
inputs from already authenticated captures, the exact SHA CI accepted, and
the regular P1 runner's scheduled checkout pinned/merged to the reviewed
code. This proposal intentionally adds NO new provider GET, workflow, cron,
GitHub permissions, service or producer concurrency; this feature cannot
fully operate in production until those acceptance gates are satisfied.

## Test gates and proof taxonomy

- Python source-free handoff tests: original A immutable, future vs cutoff,
  6 boat IDs, actual source tilt matching, independent exhibition formation,
  event-specific ranking, frozen B coefficients, Node actual 120 output,
  server save receipt and late upload HOLD.
- Existing P1 cycle tests: no research inputs leaves original baseline
  untouched, empty approved source produces research HOLD in the SAME AES
  payload, independent GitHub-like artifact readback verifies counts.
- Script CLI tests: official same-run/head/round 0600 private input accepted,
  foreign source-code commit rejected; no unauthorized source GET.
- 11-venue/132-race synthetic grid: denominator 132 without claiming 132
  forecasts; late/missing races remain HOLD.
- Source owner must authenticate actual future real preclose P1 A & B
  separately in GitHub Actions; run independent process readback; confirm
  payout/refunds/Top8/high-paying tickets with the existing bulk scorer.
  Synthetic green is NOT official real-race forecast success.

No main merge, no live parameters altered and no wagers.
