# DT-R1 executable research pipeline

## Goal

Implement the six next stages documented in `research/chatgpt_dt_r1/README.md`: real archive admission and learning; time-separated calibration; venue/timing/video evidence; ticket policy; a fair three-participant comparison; encrypted runtime and candidate updates. The owner's instruction to implement all stages authorizes this work. Production promotion and measured future accuracy remain separate acceptance decisions.

## Architecture

Keep this independent participant under `research/chatgpt_dt_r1`. Reuse the existing encrypted-history codec, official source admission, and race-development classifier. Do not read or train on the independent Codex competitor. Plain dictionary contracts join source admission, historical features, a learned conditional ranking distribution, calibration, policy, comparison, and runtime. Preserve v0 as an explicitly unvalidated reproducibility baseline.

Tech stack: Python 3.12, NumPy, SciPy, Pillow; SQLite; existing cryptography and GitHub infrastructure. Calibration is implemented locally. No new service, key, permission, paid plan, hosting, or wagering.

Spec: owner conversation; `KEIRIN_PREDICTION_ACCURACY_CONFIDENCE_SPEC_20261128.md` at main `6618214e440f13727f5ab267dfaadd1f37601d4b`; existing 20261125 detailed spec and acceptance notes.

## Global constraints and evaluation contract

- Support mathematical fields of 3–9 starters; retain every archive/calendar race and count holds, missing input, incidents, dead heats, cancellations, and unavailable results. Do not silently exclude the previously discussed race.
- The pinned two-DB archive is retrospective, previously examined data. Its naive/post-race collection clocks do not establish pre-cutoff availability. Do not manufacture cutoff timestamps or registration IDs.
- Build history from strictly earlier race days, batching updates after every whole day. Same-race agari, finish, weather backfill, payouts, and outcome-derived information are never input features.
- Train through 2026-06-30; select structure on July; calibrate on August; independently audit calibration on September; freeze before the October–November reused historical evaluation. Do not retune using final-period scores. Future shadow records have a separate cohort and authenticated-clock requirements.
- Predeclare conditional ranker candidates: base/no pair effects; full historical features with line pair effects; no-history ablation; no-context ablation when sidecars are enabled. Select by July joint top-three log loss, with fixed Hit@4 and exacta Hit@2 reported, never by final-period results.
- A single sequential conditional distribution yields trifecta, exacta, and all finishing-position marginals. No independent position-probability multiplication.
- Distinguish official half-lap agari, full final lap, and each observed segment. Missing is unknown, never fabricated physiological measurement.
- Ticket limits: <=10 odds:2; >10–20:4; >20–<100:9; >=100:12; exacta max2. The anchor is fixed before observing odds. One ticket is permitted. Unknown/late odds do not invent a budget.
- Confidence is for the selected set, calibrated and independently audited for the same model/policy/count/context. Thresholds 90/80/60%; otherwise HOLD when evidence is insufficient.
- Three-way comparison requires actual independently frozen entrant outputs and the same input/time/cohort. Missing rivals produce a pending result, never substituted models or a claimed victory.
- Only aggregate research evidence is public. Raw DBs, source pages, video, private original predictions and keys stay outside tracked files. Runtime state uses the existing owner-key encrypted-history path. Missing prior state stops, not resets.

## Tasks and ownership

- [x] T1 `data.py`, `features.py`, `admission.py`: SHA-pinned read-only archive adapter, existing official admission facade, source defect handling, strict day-lag histories, explicit missingness and coverage.
- [x] T2 `model.py`: fit conditional ranking likelihood on real past records, pair dependence, exact top-three and full rank marginals, serialization integrity.
- [x] T3 `observations.py`, `venues.py`, `context.py`, `vision.py`, `phases.py`: source-qualified geometry, crossing/segment extraction, reviewed timing, anonymous image tracking, supervised phase transitions and existing PDCA adapter. Actual rider video/phase observations remain unavailable.
- [x] T4 `policy.py`, `calibration.py`, `comparison.py`: odds/count policy, disjoint calibration/audit, all-target/common-cohort metrics and paired day-block intervals.
- [x] T5 `pipeline.py`, `cli.py`: chronological candidate selection, frozen evaluation, ablations, reproducible artifacts, input/model/source hashes, optional observations.
- [x] T6 `runtime.py`, report view, CI: immutable forecast/result revisions, append-only calendar admission, existing encryption, future shadow adapter, authenticated optional odds/calibration and candidate retraining without automatic production promotion.
- [ ] T7 real archive run, negative-path tests, independent source/code review, final evidence and draft PR. Owner: coordinator plus independent reviewer.

## Review focus

Leakage across any split or same day; odds/cutoff clock substitution; label-driven input hashes; hidden dropped races; mutable frozen forecasts; invented rival forecasts; confidence certification from training samples; conditional versus observed incident outcomes; private data in public outputs; and unsupported claims of nationwide or future completion.

## Verification

Use small synthetic tests for invariants and attacks, then a measured real-data training/calibration/evaluation run. Report those forms of evidence separately. Pin the chosen model before evaluating the final archive period. Record all unmeasured deployment/video/future conditions explicitly.
