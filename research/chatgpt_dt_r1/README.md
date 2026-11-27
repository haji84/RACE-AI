# ChatGPT DT-R1 v0 / independent research entry

## Scope

Three-way comparison: existing integrated model, Codex independent new model, ChatGPT DT-R1. This branch changes no production or rival-model files. No rival forecasts enter the model. No production promotion.

Feasibility: cycling physical simulation is established for measured conditions, but actual keirin individual power, wind exposure, tactics and fatigue are not known from a racecard. Start with a trainable latent tactical model, then validate additions using real data. The six phase rankings are hypotheses, not video-verified positions; fatigue is a latent score, not joules or a medical measurement.

- https://pubmed.ncbi.nlm.nih.gov/28121252/
- https://link.springer.com/article/10.1007/s12283-018-0283-0
- https://keirin.jp/pc/dfw/portal/guest/guide/question/race.html (official definition: agari time is final half lap, not full lap).
- Existing data inventory: docs/KEIRIN_MASTER_READBACK_20261126.md.
- Existing historical SQLite source is described in docs/KEIRIN_JOINT_FORECAST_CONTINUATION_20261125.md. No raw data redistribution authorized here.

## Implemented and locally verified

- Deterministic line-leader scenario mixture; six latent phase scores; independent from A/B.
- Grid fitting of strength, line, fatigue and temperature coefficients with joint top-3 log loss.
- Exact enumeration of ordered top-3 probabilities and consistent exacta marginal.
- Mathematical support for 3 through 9 starters, including singleton-line Girls inputs. Actual nationwide coverage remains unverified.
- Cutoff margin 15 minutes on supplied clocks, duplicate training race and future result guards.
- CLI train, forecast, chronological holdout evaluation; Hit@1/2/4/9/12, exacta Hit@1/2, log loss, Brier and coverage. For fewer possible outcomes than K, use all available outcomes.
- Seven synthetic unittest cases plus one synthetic holdout check; no real race accuracy measured.
- Git blob IDs verified against locally tested files: model ec937406f8acff378622225ca194eca4a455529f, test 46a0a4fe54a829dd6a719083e20a168387e140ac, CLI ff451fb0725bc1fc7efc127364274c5ced077143.

## Run locally (Python standard library)

From research/chatgpt_dt_r1:

    python -m unittest -v
    python run_dt_r1.py fit train.json --at <training-freeze-ISO8601> > fitted.json
    python run_dt_r1.py evaluate holdout.json --model fitted.json > report.json
    python run_dt_r1.py forecast snapshot.json --at <prediction-ISO8601> --model fitted.json > forecast.json

Input train/holdout: JSON array of {snapshot, prediction_at, official_top3, result_at}. Snapshot fields: race_id, as_of, published_cutoff_at, competition, line_groups, riders (each car, competition_points, recent_form_score, h_count, b_count, style). Existing raw snapshot may include additional metadata. Do not use the public ranked-ticket projection as raw features. Do not manufacture a historical cutoff, form value, line, or capture time.

Caller must independently establish source provenance and cutoff/result clocks; the CLI checks declared timestamps only. The original encrypted forecast and result admission must be performed by the existing authorized environment. Local execution is not attestation. Historical records lacking authentic pre-cutoff source receipts can only support explicitly retrospective research, not prospective proof.

## Next acceptance gates (not completed)

1. Read-only adapter from independently admitted historical snapshots + official results. Check source SHA, timestamps, identities, duplicate IDs, missingness. Count all calendar races, separately report holds/cancellations/dead heats.
2. Fit on older records; calibrate on a separate later set; freeze before final untouched evaluation. Compare same inputs, time, races, fixed K. No training on rival output.
3. Add separately evidenced venue geometry, rider-by-venue historical full-lap/half-lap/segment times, weather, actual phase labels; verify each added feature via ablation. Neither video acquisition nor complete physical simulation is implemented.
4. Calibrate confidence by ticket count and context. Proposed user thresholds 90/80/60%; all current confidence output HOLD. Do not promote on sparse observations or use raw scenario frequency as calibrated probability.
5. Three-way prospective shadow comparison with existing integrated model and independent Codex model. Compare fixed Hit@1/2/4/9/12 (exacta 1/2), proper scores, coverage, day-block paired uncertainty, resource use. Report simulated payout only with independently verified payout data and same evaluation policy. No wagers needed.
6. Integrate with authorized encrypted pre-cutoff storage and independent readback, official scoring and dashboard after review. No main merge or production change until owner approval and real evidence.

Historical training, calibrated prediction, official proof, complete nationwide automation, and competition victory are NOT established by this v0.
