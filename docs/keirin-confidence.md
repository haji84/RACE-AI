# Saved confidence for KEIRIN forecasts

## What the four levels mean

The reader displays 激アツ, 高, 中, or 低. These levels compare the coherence of a forecast across its saved six-phase scenario universe. They are provisional research classifications, not calibrated hit probabilities. Missing or unsuitable evidence is 未評価. Historical authored labels remain historical labels and are not silently replaced by this new rule.

The first rule version is `research-coherence-v1`. Its thresholds are explicit design choices awaiting prospective validation against subsequently observed results. They are not fitted claims about past accuracy, and the feature does not promote model weights or place wagers.

## One evaluator and a fixed denominator

`race_ai/keirin_confidence.py` evaluates both automatic and newly authored selections. It uses the complete independent universe of plausible outcomes, not a universe reconstructed from the selected tickets.

The fixed-denominator metrics are:

- `axis_top2_share`: concentration of possible winners in the two leading winner candidates.
- `pair_top4_share`: concentration of first/second orders in the four leading pairs.
- `triple_top6_share`: concentration of first/second/third orders in the six leading triples; not a two-car grading requirement.
- `scenario_coverage`: selected tickets' coverage across the complete saved universe.
- `major_uncovered_ids`: important branches whose candidate outcomes are not fully covered. High and hot require none.
- `late_phase_axis_presence`: an explanation-only position metric when the source actually has car orders. Narrative prose is never converted into an invented order.

| Grade | Top-two winner share | Top-four pair share | Top-six triple share (3t) | Coverage |
| --- | ---: | ---: | ---: | ---: |
| 激アツ | 0.85 | 0.85 | 0.90 | 0.90 |
| 高 | 0.70 | 0.70 | 0.80 | 0.80 |
| 中 | 0.50 | 0.50 | 0.60 | 0.50 |
| 低 | Below the medium requirements | | | |

These shares describe the saved scenario representation, not empirical outcome frequencies. Automatic B's existing relative research weights remain explicitly uncalibrated. New authored universes use equal branch weights and explicitly listed outcome candidates. Ticket count is never an independent bonus. A rollover subset retains its parent's entire universe, so removing tickets cannot increase confidence.

The source status and six-phase evidence must be complete enough for grading. An unknown lineup, conflicting required fields, unavailable market candidates, or an invalid/pre-cutoff timing relationship cannot produce a high grade.

## Original-preserving storage

The generator and its existing prediction digest stay unchanged. A sibling `confidence_assessment` contains the schema and rule version, race, actual assessment time, published cutoff, original prediction hash, source facts hash, scenario-universe hash, and separate A/B evaluations.

Creation happens immediately after a new forecast, before encryption, and at least 65 seconds before the published cutoff. Both encrypted A/B arms and the official source bundle retain the same sidecar. Readback validates their equality and source/time bindings. Older records with no sidecar remain readable; readback does not create or overwrite a grade.

The display-only view contains the existing minimized source facts. Its validator checks the known version, grade/metric structure, ticket identity and baseline/time bindings. Full source reconstruction is performed at generation, seal and decrypted-source verification. The browser displays saved reasons and grades without running the research scorer.

Adjusted A/B forecasts have different tickets and do not inherit baseline grades. A three-car grade is never copied to a two-car forecast.

## New authored normal and rollover forecasts

`race_ai/keirin_authored_confidence.py` creates fresh records with `confidence_universe` and a `confidence_assessment` whose `evaluations` contains one `selected` entry. A universe must declare the new `RACE_AI_KEIRIN_CONFIDENCE_UNIVERSE_V1` format, `authored_goals`, and `independent_preselection_v1`. Merely renaming a legacy `goal_candidates` property does not establish independent coverage.

The selected forecast digest covers its original body. It excludes its own sidecar and, for a two-car normal record with a known `rollover` child, that child's sidecar. The child's original tickets, universe, times and other body fields remain covered, and the child's sidecar is validated independently. This avoids self-reference and cross-runtime floating-point serialization of assessment metrics.

The creation command is:

```sh
python -m scripts.keirin_note_create_forecasts \
  --input /absolute/private/new-request.json \
  --output /absolute/private/empty-new-output
```

The input must be mode 0600, and the existing empty output directory mode 0700, both outside Git. There is no timestamp override or overwrite mode. All records pass evaluation and validation before writing begins. The command uses the existing importable dated files: `forecasts.json`, `two_car_forecasts.json`, and `three_car_rollover_forecasts.json`. A two-car rollover is an independent saved child in `two_car_forecasts.json`; it requires the corresponding normal record. Output prints counts only. The existing private import/encrypted-feed workflow carries the files to the reader.

The request has `schema: RACE_AI_KEIRIN_NEW_AUTHORED_FORECAST_REQUEST_V1` and a `races` array. Each race supplies a full `universe` and up to four `selections`, one per market/strategy combination. A selection contains exactly `market`, `strategy`, `headline`, `reason`, `risk`, and `tickets`. Tickets contain `combo` and `role`. Synthetic executable examples are in `tests/test_keirin_authored_confidence.py`; they are not real forecasts.

## Reader behavior

The current reader validates the new sidecar before exposing it through `M.forecast()` or `M.frozenArm()`. It normalizes legacy labels for display, provides a high-or-above filter, and shows saved reasons, limitations, rule version and assessment time. Filtering a nationwide row operates on each arm: an A grade of high does not bring a medium B arm into the filtered results.

The existing Site uses the same model/feed/assessment adapter. Its standalone daily view stays separate from the canonical app's modal shell. Dated archive forecast packets retain their original bytes and labels.

## Verification boundary

Synthetic tests establish reachable high/hot outputs, missing-evidence and time rejection, tamper rejection, cross-market separation, no increase from removing tickets, encrypted round trips, legacy readability, and JavaScript/Python interoperability. They establish functioning software, not forecast profitability or calibrated confidence. Prospective observed results remain separate and must be used for any later calibration claim.
