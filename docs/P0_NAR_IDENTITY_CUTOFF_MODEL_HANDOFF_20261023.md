# P0: NAR official-format CSV -> four-model identity/cutoff handoff

Date: 2026-10-23 JST. Issue #67 / #68; existing Draft PR #71.

## Why this bridge was needed

NAR's [May 2026 CSV manual](https://www.keiba.go.jp/pdf/manual/data_pdf_manual.pdf) documents a 66-column race-list and 36-column horse-list pair, with a separate 54-column result/payback file. The PR #71 `nar_official_csv_adapter` already parses a locally provided approved pair without retrieving source material automatically. Its output deliberately stops **before model evaluation** because the official CSV alone does not supply:

- a separately authenticated **official sales cutoff** (the visible HHMM is scheduled START, not the sales deadline);
- stable cross-day horse IDs for permitted historical joining (a name and number are not a durable key);
- the full model-required historical features and environment observations;
- a reliable external timestamped pre-cutoff freeze and an authorized result feed.

## Added implementation

`race_ai/nar_model_handoff.py` now joins a *prior staged official-format CSV* with three independently supplied, rights-reviewed inputs:

1. **A full normalized research input** (`RACE_AI_NORMALIZED_FEATURE_FEED_V1`) containing a `RACE_AI_FOUR_SPORT_EVIDENCED_SNAPSHOT_V1` horse model snapshot. Each feature must have its own published/captured timestamps and rights-scoped `source_ref`, `source_rights_ref`, sample size and transform version. Unknown features cannot be filled by fabricated values.
2. **An independent stable-horse-ID witness** (`RACE_AI_NAR_INDEPENDENT_IDENTITY_WITNESS_V1`), mapping race horse number, frame, actual name and an independently verified durable horse identifier. It must match every entry in the immutable NAR staged CSV and the model's identities, with no duplication or unlisted horse.
3. **An independent cutoff witness** (`RACE_AI_NAR_INDEPENDENT_CUTOFF_WITNESS_V1`) containing the same race ID, the actual sales cutoff, source rights and timestamps. A separate verifier callback must authenticate it. Its time must match the model's cutoff, be strictly before scheduled start and strictly after delivery time.

Both witnesses require independent, purpose-scoped rights checks for analysis, private retention and private derived output, and a separate external-verifier callback. **Callbacks are extension interfaces; returning `True` is not proof of a rightsholder license or official publication time.** Actual production implementation of source/authentication remains necessary.

The bridge calls the existing `permissioned_source_delivery.deliver` after confirming the CSV stage SHA, participant/race/venue/day/surface/distance and source timing. It uses the already implemented 4 research models and does not create a fifth model.

The output includes CSV source SHA, stage SHA, independent witness SHA and model output SHA. It remains **`NAR_PRIVATE_RESEARCH_UNFROZEN`**, `official_prediction=false`, `external_freeze_receipt=null`, `can_count_in_hit_at_8=false` even when the test callbacks accept.

## Important restrictions

- No NAR download, source scraping, historical training data capture, live predictions, betting, billing or deployment was carried out.
- The tests in `tests/test_nar_model_handoff.py` use an explicitly fictional eight-horse 2030 race and callbacks that only test shape and business logic; they are **not independently signed authorities**.
- Never treat a post-race official format CSV as a forecast snapshot. Its outcome, sectional and popularity fields are rejected by the upstream NAR stage.
- No durable horse identifier is generated from horse name / jockey / trainer; identifiers must come from an independently authorized entity mapping.
- If the official sale cutoff or any mandatory input is missing, leave the race as `NO_FORECAST` with its exact reason.
- The immutable trusted remote freeze writer, independent receipt verification and result revision chain remain separate missing components.
- Private input/output must not be committed to this public repo; signed policy records must be reviewed against real rightsholder terms.

## Real E2E next check

1. Independently confirm the actual machine collection/analysis/retention rights for **one real provider** and the allowed time, format and request quota.
2. Acquire a permitted current upcoming race's original pre-cutoff entries and authenticated cutoff + stable IDs.
3. Normalize available historical features (and document every transformation, sample size and missing feature) to the already existing model schema.
4. Run this handoff, then fix the model ID/version and maximum 8 trifectas; remotely persist the same bytes + SHA before official sale cutoff. Verify remote server receipt and readback.
5. After final official outcome, append result revisions without modifying forecast; only then calculate measured Hit@8.

**Acceptance**: this PR advancement is limited to the synthetic schema/identity/cutoff join. There is still no permission-admitted real-race E2E or externally frozen forecast. A single real E2E is a milestone, not final full-coverage or 98% verification.
