# Offline chronological model training

`race_ai/model_training.py` provides deterministic local learning, validation-only calibration and a final-test report. It uses no network, external provider, API key or paid model. Every artifact and generated prediction stays **UNVALIDATED**, research only, and ineligible for live purchase recommendations. An improvement in a synthetic or retrospective report does not promote a model.

## Public contract

- `train_and_evaluate(records, configuration)` returns `{artifact, manifest, report}`.
- `export_model(run_or_bundle)` returns canonical JSON containing `{artifact, manifest}`.
- `load_model(json_text)` verifies hashes, schema, finite values and research-only status.
- `predict_with_artifact(bundle, pre_race_record, generated_at=None)` returns the existing `prediction.build_prediction` payload, including 120 triples, position marginals, model version hash, selection reason and an empty recommendation list. Omitting `generated_at` uses the current UTC clock. The actual `prediction.save_prediction` call must still succeed before the race; producing this payload is not a save or proof of a pre-race observation.
- `TrainingError` derives from `prediction.PredictionError`. The automatic worker should record the reason and skip inference on this exception, without substituting zero values or inventing feature snapshots.

Run the offline CLI with explicit local files:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m race_ai.model_training `
  --dataset C:\path\features-and-labels.json `
  --config C:\path\training-config.json `
  --output C:\path\new-research-run.json
```

Output creation is exclusive: an existing report file is not overwritten. The command prints `UNVALIDATED_OFFLINE_RESEARCH` plus the artifact hash. Invalid inputs return a nonzero exit code. Dataset/config/model JSON rejects duplicate keys and nonfinite constants; input size, record count and optimizer iterations are bounded.

## Explicit feature/label boundary

Each training record has exactly these fields:

```json
{
  "race_id": "synthetic-01",
  "race_start_at": "2026-10-01T03:00:00Z",
  "as_of": "2026-10-01T02:50:00Z",
  "source_kind": "synthetic",
  "boats": [
    {
      "lane": 1,
      "features": {"historical_win_rate": 0.25},
      "available_at": "2026-10-01T02:49:00Z",
      "captured_at": "2026-10-01T02:49:00Z",
      "generated_at": "2026-10-01T02:49:00Z",
      "source_ref": "synthetic-feature-snapshot"
    }
  ],
  "label": {
    "status": "settled",
    "confirmed": true,
    "top3": [1, 2, 3],
    "available_at": "2026-10-01T03:05:00Z",
    "captured_at": "2026-10-01T03:05:00Z",
    "source_ref": "synthetic-official-label"
  }
}
```

The example shows one boat for readability; an input must contain six distinct lanes. It is synthetic, not an actual race. Inference uses the same record with `label` omitted; supplying a label to inference is rejected. Current actual ST, actual course, finish, final payout and final odds cannot be added to the feature dictionary or record. Missing values, unknown extra fields, NaN, infinities, duplicate race IDs, repeated lanes and unconfirmed labels are rejected.

`source_kind` is `synthetic`, `operator_supplied` or `official_source_attested`. These are declared provenance categories, not independent authentication. `source_ref` must identify the retained immutable source/derivation record. All feature snapshots require `available_at <= captured_at <= as_of < race_start_at` and `generated_at <= as_of`. Official labels require `race_start_at <= available_at <= captured_at`. Fractional timestamps retain microseconds through the existing prediction time parser.

Supported feature names and ranges are deliberately narrow:

| Name | Range | Interpretation |
| --- | --- | --- |
| `lane_bias` | −1,000,000 to 1,000,000 | Explicit pre-race lane feature |
| `historical_win_rate` | 0–1 | Past-only first-place fraction |
| `historical_mean_st` | 0–1 | Past-only mean start seconds |
| `motor_residual` | −1 to 1 | Past-only adjusted motor residual |
| `exhibition_time` | 0–100 | Available pre-race exhibition seconds |
| `exhibition_st` | 0–1 | Exhibition start seconds, never current actual ST |
| `predicted_course` | 1–6 | Forecast course, never current actual course |
| `market_implied_win_probability` | 0–1 | Market feature known by cutoff |

Every boat must supply exactly the selected feature names. This version does not impute missing information. Feature derivation must independently exclude the target race and post-cutoff history revisions. A renamed future outcome cannot be detected from numeric values alone; truthful provenance and source lineage remain required. Odds-feature artifacts are marked `uses_odds: true` so odds-free and odds-using models remain distinguishable.

## Chronological phases and frozen knowledge

Configuration requires exactly:

```json
{
  "feature_names": ["historical_win_rate"],
  "train_end_at": "2026-10-01T08:00:00Z",
  "validation_end_at": "2026-10-01T16:00:00Z",
  "evaluation_as_of": "2026-10-02T01:00:00Z",
  "epochs": 100,
  "learning_rate": 0.1,
  "l2": 0.02,
  "temperature_grid": [0.5, 1, 2],
  "calibration_bins": 10
}
```

The boundaries must be increasing and evaluation cannot be in the future relative to actual execution. Sort by race start and race ID; input order cannot randomize or change the phases. Assign starts before `train_end_at` to training, starts from that boundary up to `validation_end_at` to validation, and later starts before `evaluation_as_of` to final test.

- Training label availability/capture must be at or before `train_end_at`.
- Validation label availability/capture must be at or before `validation_end_at`; its decision `as_of` cannot precede `train_end_at`.
- Final-test labels must be available/captured by `evaluation_as_of`; its decision `as_of` cannot precede `validation_end_at`.

The decision-time conditions prevent a model frozen after a race's feature cutoff from being applied to that earlier cutoff. Late labels produce a rejection, not an advantageous silent reassignment. Each phase needs at least one scorable normal result. Ties, cancellation/no contest, postponement and special outcomes are explicit exclusions with race ID, phase and reason; they are not relabeled as ordinary finishing orders. The report contains all scored race IDs per phase and excluded records. The one-race minimum makes the software testable; it does not establish an adequate sample for model adoption.

## Fitting, calibration and research selection

The uniform baseline assigns 1/120 to every ordered triple. The fitted model uses a linear log-worth for each boat, with no common intercept because it cancels from the ranking probabilities. Fit feature means and population scales on **training boats only**; a constant feature uses scale 1. Standardized inputs are clipped to ±8, weights to ±10 and log-worths to ±20 for a bounded numerical model. These bounds are part of the artifact's interpretation, not hidden postprocessing.

Optimize mean strict top-three Plackett–Luce negative log likelihood plus `0.5 * l2 * sum(weight²)`. Full-batch gradient descent starts from zero coefficients, uses fixed input ordering and deterministic backtracking to avoid an increasing objective. Save coefficients, feature scaling, optimizer settings, iteration count and initial/final objective. This is an interpretable fitted baseline, not a neural network or a claim of convergence to the best possible racing model.

Choose a positive temperature from the predefined grid by validation log loss only; ties prefer the temperature closest to 1. A temperature scales the linear scores before the existing bounded Plackett–Luce probabilities are generated. This is a constrained validation-only temperature calibration procedure inspired by the general approach in [Guo et al., 2017](https://proceedings.mlr.press/v70/guo17a.html); the paper does not establish its performance for these race data.

Retain the fitted family as the research choice only if its validation log loss improves over uniform by more than 1e-9. Otherwise select uniform. Freeze this choice, temperature, scaler and coefficients **before** scoring final-test rows. The final test never influences artifact parameters, hashes, calibration or selection; changing final-test labels/features changes only the report. Inspecting a final test and rerunning with tuned settings consumes that holdout and needs a newly declared unused period.

## Artifact, actual creation and worker integration

The artifact records implementation/schema version, coefficient/scaler interpretation, calibration, training/validation data hashes and race IDs, source categories, explicit odds use, selection reason and fixed UNVALIDATED status. Its SHA-256 covers canonical sorted-key JSON before insertion of the hash field. It excludes final-test data and wall-clock fields so identical training/validation data and settings reproduce the same artifact in the supported runtime. The whole report has a separate dataset hash including final-test inputs.

The manifest records the **actual UTC execution time** at which the fitted/calibrated artifact was created, its artifact hash, a retrospective marker, and its own integrity hash. Artifact reproducibility does not erase this availability time. Loading validates both hashes. These hashes detect corruption; they are not signatures or proof against a privileged operator who rewrites the file or clock.

For future automatic inference:

1. Load a retained model bundle with `load_model`.
2. Read only observation-store versions that were available, captured and actually saved by the requested `as_of`, using the store's pre-race eligibility filter. Exclude final odds and current actual/result information. Aggregate source references and timestamped feature derivation lineage.
3. Package an **unlabeled** record with the artifact's exact feature schema.
4. Call `predict_with_artifact`. It requires both actual manifest `created_at` and calibration label cutoff to precede the requested `as_of`; a model trained today cannot be asserted to have existed for a historical race.
5. Pass its unchanged result to `prediction.save_prediction` before race start. That API independently uses actual server save time and immutable versions. Failure must remain a recorded skip.

The current historical three-endpoint observations captured after their race are not eligible pre-race training snapshots merely because a page describes pre-race exhibition or odds. Do not backdate capture/save times or call retrospective scores live performance. The worker must keep the baseline's UNVALIDATED gate; `eligible_for_live_recommendations` remains false. The pipeline reuses the common money allocation gate and produces zero recommended spending, rather than deriving fictional ROI or hypothetical purchases from a model score.

## Reports and evidence

For training, validation and final test, score uniform and fitted models on the same normal races through `prediction.py`'s metric definitions: race/ticket counts, natural-log loss, multiclass Brier (sum over 120 outcomes) and reliability bins over all 120 triple events per race. Empty bins have null rates. Display the exact evaluated period and sample counts. The report is always `retrospective_research: true`, `actual_pre_race_performance: false`, even for source-attested records.

`tests/test_model_training.py` verifies the known uniform metrics, useful learning on a deterministic synthetic pattern, chronological phase IDs, late/future evidence rejection, held-out invariance of artifact parameters, baseline retention when validation worsens, hash/read integrity, artifact-availability gates, unsupported outcomes and the real offline CLI. `docs/evidence/offline-training-2026-10-15.json` saves a synthetic run, reproducibility comparison and final-label perturbation proof. None of this is evidence of real held-out accuracy or calibration. Actual adoption needs retained real source/availability evidence, preregistered unused evaluation periods, adequate samples, independent review and a separate explicit promotion process.
