# Research prediction foundation

`race_ai/prediction.py` adds a local, interpretable research baseline, immutable SQLite prediction/result records and as-of evaluation. Every forecast and evaluation remains `research_only: true`, `validation_status: "UNVALIDATED"`, with `purchase_decision: "skip"` and an empty recommendation list. No fitted accuracy, calibration, profits, live data collection or production acceptance is established by synthetic tests.

## Ranking model

`plackett_luce(strengths_by_lane)` requires six distinct boat identities 1–6 and finite positive numeric strengths between 1e-9 and 1e9. For ordered boats a, b, c, probability is the product of choosing a from all six strengths, b from the five remaining strengths, and c from the four remaining strengths. It enumerates all 120 strict top-three orders and normalizes their total mass. It also enumerates 720 full orders to return first-through-sixth position marginals and top-three probabilities for each boat.

This follows the standard Plackett–Luce sequential ranking construction documented by the [PlackettLuce authors](https://hturner.github.io/PlackettLuce/index.html) and their [research paper](https://arxiv.org/abs/1810.12068). The implementation uses the strict-order model, without the paper's tie extensions. Strength values are supplied or derived by the simple history baseline; they are not trained parameters or certified ability scores. Probability arithmetic uses finite double precision, independently of the fixed-decimal money engine. Model probabilities and rounded money-contract inputs must remain distinguishable; probability normalization does not establish predictive accuracy.

Uniform strengths give probability 1/120 for each triple, 1/6 for each boat at each position, and 1/2 for each boat's top-three finish. These are synthetic mathematical baselines, not boat-race observations.

## Forecast input and output

`build_prediction(data)` requires exactly:

```text
race_id, race_start_at, as_of, generated_at,
model_id, model_version, selection_reason, boats
```

Each of six `boats` requires `lane`, `strength`, `available_at`, `captured_at`, `generated_at`, `source_ref`, `feature_kind`. Supported feature kinds are `pre_race_strength`, `history_baseline`, `uniform_baseline`. Optional explicit history fields are `racer_id`, `predicted_course`, `sample_n`, `historical_first_count`. Other fields, including current-race actual ST, actual entry course, finish, payout and final odds, are rejected. The current-race outcome cannot be supplied through a generic free-form feature object.

All timestamps require an ISO date/time, seconds and timezone, with up to six fractional-second digits. Invalid calendar values, offsets and naive times are rejected. Temporal comparisons retain microseconds; they do not truncate a future observation into the cutoff. The prediction requires `as_of <= generated_at < race_start_at`; each evidence record requires `available_at <= captured_at <= as_of` and its source `generated_at <= as_of`. A caller remains responsible for truthful timestamps, source rights, provenance, and the absence of hidden leakage in supplied strength values. These checks validate the explicit contract; they cannot establish the origin of a fabricated strength or timestamp.

The result includes normalized `inputs`, model identifiers and selection reason, 120 `triples`, six `marginals`, normalized `strengths`, explanations based only on supplied fields, an explicit uncalibrated uncertainty marker and missing-history identities, and `content_sha256`. The hash is over canonical sorted-key UTF-8 JSON before the hash field is inserted. Rebuilding the same inputs yields the same payload and hash.

## History baseline

`build_history_baseline(db, race_id=..., entries=..., race_start_at=..., as_of=..., generated_at=...)` reuses `core.utc`, `core.summarize` and the existing `starts` records. Each of six entries must have exactly `lane`, a four-digit `racer_id`, and an explicit `predicted_course`. Racers are distinct and predicted courses form a permutation. Predicted course is never replaced by the current race's actual course.

Eligible source revisions must be publicly available and captured by the cutoff. The latest eligible source revision is selected per historical race/boat before filtering by racer and course, so a course or identity correction cannot leave its superseded row in the model. The target race, races at/after the cutoff and absent starts are excluded. Up to 20 latest same-predicted-course records feed the untrained smoothed worth `(historical_first_count + 1) / (sample_n + 6)`. The timestamped source-identity digest and counts are retained. With no eligible history, the prior worth is 1/6 and the racer appears in `missing_racer_history`.

This baseline uses historical first-place counts. It does not claim that ST, motors, video, odds, weather or entry interactions contributed to its explanation. Missing/unsupported historical finish dispositions are a modeling limitation; the underlying schema does not retain every disqualification reason. The source-level generated timestamp represents eligibility of the historical evidence snapshot; the forecast's own computation time is recorded separately. Using supplied history does not independently establish source reuse permission.

## Immutable storage and actual save time

Use the existing `core.connect(...)` connection, or equivalent SQLite connection, with `setup_prediction_store(db)`. The setup creates `prediction_versions`, `result_revisions`, indexes and triggers rejecting UPDATE/DELETE on either table. Setup initializes schema using `executescript`; callers should initialize it before composing unrelated transactions.

`save_prediction(db, forecast)` rebuilds the payload from its normalized inputs and rejects changed hashes, distributions or derived metadata. It obtains `saved_at` from the server UTC clock; a caller cannot supply a backdated save timestamp. It requires `generated_at <= saved_at < race_start_at`. The content hash is `version_id`; identical retries before start reuse the original immutable record. A changed source/cutoff/model/version produces another record. A retry at/after start is rejected; existing records remain readable through `export_prediction(db, version_id)`, which returns canonical JSON. Historical forecasts built after the event cannot be inserted as pre-race performance evidence through this API.

`save_result_revision(db, official_result)` requires `race_id`, `race_start_at`, `status`, `confirmed: true`, explicit `payouts`, `available_at`, `captured_at`, `source_ref`; normal `settled` results additionally require three distinct `top3` boat identities. It reuses the money engine's result/payout validation and requires `race_start_at <= available_at <= captured_at <= saved_at`. A confirmed result/source remains a caller assertion that must be supported by the official-data adapter. An identical result retry is idempotent. Changed results append a numbered revision with `supersedes_id`; a correction cannot predate the stored latest source availability/capture. Forecast payloads are never rewritten by a result correction.

SQLite immutability and payload hashes protect the normal application path, not an attacker with administrative access to the database file or process clock. Production source/saved-time evidence needs an operational access boundary and external audit evidence. Synthetic tests mock only the server clock to exercise historical cases; they do not prove a forecast was really observed before a live race.

## Evaluation and comparable cohorts

`evaluate_predictions(db, as_of=..., model_ids=None, calibration_bins=10)` uses only saved versions known at evaluation cutoff and saved before the race. It takes the latest pre-race forecast per `(race, model_id, model_version)`. For each race it uses the latest result revision whose availability, capture and actual save all precede the evaluation cutoff. Thus an official correction changes a later report without rewriting an earlier as-of report or prediction.

Only normal strict-order results are scored. Pending results, ties, cancellation, refunds/no-contest and schedule mismatches are returned with explicit exclusion reasons. A missing result is not treated as a model miss. The report returns model version, selection reasons, race IDs, race count, ticket count, mean multiclass Brier score (sum over 120 classes, no division by 120), mean natural-log loss of the realized triple, and calibration bins. Calibration bins contain all 120 predicted triple events per scored race, count positive outcomes, and show mean predicted probability versus observed frequency; empty bins return null rates. Low-probability bins can dominate this view, so it must not be presented as proof of useful calibration.

`compare_models(db, model_ids, as_of=..., calibration_bins=10)` requires at least two distinct model IDs. It scores only shared races with one unambiguous version per requested model and equal information cutoffs. Missing/ambiguous model cohorts and differing information cutoffs are recorded as exclusions. The result includes `common_race_ids`; models with different evaluated race sets must not be compared as if they used this shared cohort. No automatic model promotion occurs.

Uniform forecasts against one synthetic normal result have multiclass Brier 119/120 and log loss ln(120). These expected values verify metric definitions only. Adoption still requires preregistered criteria, held-out races, source/as-of evidence, adequate samples, calibration checks, stability and comparative improvement.

## Verification and remaining integration

`tests/test_prediction.py` covers enumeration, conditional probabilities, all six marginal positions, finite input validation, forbidden current outcomes, microsecond cutoffs, immutable/idempotent storage, actual server save-time gates, reproducible exports, result correction history, as-of evaluation, shared model cohorts and historical source-revision filtering. `docs/evidence/prediction-foundation-2026-10-15.json` contains explicitly synthetic/simulated evidence.

This module is a technical foundation. It is not connected to the rights-gated official collector, automatic prediction scheduling, persistent cloud storage, browser research views, production access controls or multiday accuracy measurement. Those integrations must retain the research-only gate and pre-race save evidence; the money allocator must not receive a fabricated `validated: true` flag from this baseline.
