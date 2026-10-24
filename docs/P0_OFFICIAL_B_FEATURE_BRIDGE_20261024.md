# P0 Official B → PR71 source-derived feature bridge (2026-10-24)

Scope: Issue #67, existing Draft PR #72. Strict official-B parser is pinned from Draft PR #64 at `761247bee0209e37b1af6b8885e92cad3e9260a5`. PR71 feature inventory is pinned in the one-shot workflow at `5d4be4326b4fba321507a08f09e1eb7b661d027e`. No model coefficients, historical forecasts, or official results are changed.

## Implemented

`race_ai/boat_b_feature_bridge.py` accepts an **already extracted and strictly parsed** B day in memory: 6-lane entrant identities, statistical detail records, scheduled B closing times, exact daily official archive URL and SHA256. Strictly checks:
- archive day/path versus each race ID; 6 unique lane and 4-digit registration IDs for each race; details-to-entrant equality and equipment allocation; no missing venue race in announced cutoffs
- numeric types and ranges, no NaN, no fake defaults, dates with timezones
- pinned PR71 required runner/environment feature names; rejects unknown mapping drift

For each entrant it creates **three non-admitted partial research candidates** (not probabilities):

| Official B parsed field | Proposed PR71 required key | Transform |
| --- | --- | --- |
| `national_win_rate` | `ability` | ten-point rate / 10 |
| `local_win_rate` | `course_compatibility` | ten-point local rate / 10 |
| `motor_top2_rate` | `motor_form` | percentage / 100 |

These linear scalings are *engineering proposals*, not evidence of predictive quality or calibration. B also has nationwide/local top-2 rates and boat top-2 rate, but these are not silently repurposed as `recent_form`, `finishing_power` or `stamina`.

Each transient candidate contains source field/unit, transform ID, original B archive URL and SHA256, a **claimed/unattested** capture clock, and explicitly `published_at=null`, `sample_n=null`, `source_rights_ref=null`, `independently_admitted_for_pr71=false`. Thus no PR71 `validate()` admission or official prediction can occur from this bridge alone. Strict release guards must remain external and evidence-backed. A previously published B artifact observed *after* the race is a historical syntax experiment, **not** proof its values were available before the race.

For the current pinned PR71 boat inventory: 11 required runner fields × 6 plus 9 environmental fields = **75** per race. B supplies 3 candidate values per runner, i.e. 18 per race. **57 required slots are not even candidate-covered**, and **all 75 remain unadmitted** without verified source publication time, sample sizes, rights, source availability at the prediction time, and required companion inputs. `private_candidate_projection` is transient; public CI logs print **only** `public_audit` counts and non-sensitive archive SHA, never racer fields, source rows or features.

## Acceptance evidence and limitations

- Local synthetic unit tests: `tests/test_boat_b_feature_bridge.py`, no network.
- Live one-shot GitHub workflow: `.github/workflows/p0-one-shot-real-b-parse.yml` uses 1 bounded historical official archive GET, PR64 strict parsed detail and pinned PR71 feature inventory. It records the per-race aggregate conversion and missing counts without storing raw archive/entrant records.
- The official publication of daily national/regional race card archives is documented at https://www.boatrace.jp/owpc/pc/extra/data/download.html .
- A publicly viewable download is not proof that its automated persistence, commercial reuse, modeling or re-publication uses are granted; independently check terms for the precise intended workflow.

**Next steps:** independently document per-field publication/revision/capture evidence and statistical `sample_n`, supply the 57 missing slots from reliable pre-cutoff sources where truly available, validate PR71 research input contract and chronological availability, freeze real future race predictions with independent server receipt, then check final official results/refunds/revisions. Do not manufacture missing data or use post-event results or odds as model inputs.
