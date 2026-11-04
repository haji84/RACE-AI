# Horse history conversion and four-model handoff (2026-11-05)

Existing PR71 only. This implements the missing conversion, not a new prediction family. Native model coefficients, original prediction files, main, automatic tasks, workflow schedules and external infrastructure are unchanged.

## Executable path
`race_ai.horse_history_features.derive(history, target, as_of=..., reference=...)` converts source-linked historical observations. It returns actual calculable fields, explicit omissions, each source lineage and a content hash. `build_snapshot` constructs the existing input schema only when required facts are present. `run_existing_four` calls the unchanged `four_sport_model_suite.run_suite`, verifies the native suite and reports all four original Top8s, every horse's first/third-place marginal score and model votes.

A marginal score is NOT a calibrated win probability. Source permission is never granted by this module. The original real-source callback remains required.

## Frozen research transformations
Let `q = 1 - (finish - 1)/(field_size - 1)` for numeric completed finishes. All following transforms are **unvalidated engineering proxies**, not trained or clinically/biologically measured horse abilities. They do not adjust race class, track variants, or opponent quality.

| Native field | Transformation and actual support required |
|---|---|
| ability | Mean q for prior completed races on the target surface |
| recent_form | Mean q weighted 3:2:1 for the latest three completed races, or 2:1/1 for fewer |
| start_reliability | Fraction without a positively observed start-incident flag; absent comments are not normal starts |
| finishing_power | Mean `0.5+0.5*(last_corner_position-finish)/(field_size-1)` |
| course_compatibility | Mean q for prior starts at the target venue/surface; no such start stays missing |
| stamina | Mean q for observed target-surface starts at least as long as the target distance |
| tactical_adaptability | Equal mean of observed regime means (front/stalking/closing from first-corner percentile); at least two regimes required |
| consistency | `1-2*population_std(q)`; at least two completed starts required |
| speed_figure | Midrank percentile of elapsed mean speed against an earlier, disjoint, source-authorized TRAIN reference at the same surface/distance; no target-field min-max |
| closing_sectional | Mean `1-(last3f_rank-1)/(field_size-1)` from the actual within-race sectional rank |
| jockey_fit | Mean q for the current confirmed jockey/horse pair, using a genuine identifier |
| distance_surface_fit | Mean q on the same surface within 200 m of the target distance |

These correlated summaries are not twelve independent sources of information. A high rank proxy alone does not justify a high probability. The 200 m rule and all transforms must be tested chronologically before adoption. Result after nonfinish, missing section data, unknown rider, and untried venue are NOT imputed with zeros, 0.5, or another feature.

`fit_reference` requires earlier capture/fit times, no future records, a TRAIN role, content hashing and real-source authorization. A synthetic reference cannot enter real-source derivation. Unknown original publishing timestamps remain null in source lineage; derived values are timestamped at calculation time, not backdated.

## Actual private execution
Ten registered Keio horses were linked to JRA horse IDs and 22 historical database records. Fifty derived feature observations were calculated, with 70 of the required 120 remaining absent. This is a source-linked search transcription, not retained first-party HTML bytes or an independently authenticated data feed. Actual history rows, names, per-horse values and prediction originals remain private in the conversation; they are not uploaded here.

The old 61-horse registration audit is retained unchanged. This work does not imply detailed histories were verified for all remaining 51 horses. Its publicly indexed external speed indices are not silently promoted into the mandatory features.

## Live acceptance NOT completed
- All four weekend race forecasts: **not generated**.
- All required features for all horses: **not complete**. Single-start horses cannot have observed multi-start consistency; unseen venue/jockey combinations are missing. Solving this requires a separately validated partial-input/prior policy, not filling fictional values.
- Actual numbered cards, official cutoff and race-time environment: not yet supplied.
- The native horse schema requires `course_cushion` for dirt; the JRA published cushion metric is for turf. The adapter refuses that mismatch rather than inserting an invented dirt cushion.
- Jump racing remains outside this flat-history route.
- Historical calibration, prospective hit rate, return rate and actual betting EV: **not measured**. The EV function is conditional arithmetic, not evidence that calibration or odds availability has been verified.

Official references: https://www.jra.go.jp/faq/pop02/2_2.html (Thursday entries are initially without numbers); https://www.jra.go.jp/keiba/baba/cushion/ (turf cushion).

## Tests
`python -m unittest discover -s tests -p 'test_horse_history*.py' -v`
Local feature tests were observed failing before implementation. Native integration tests require the existing repository modules and run in existing PR CI; their sources are fictional. No synthetic test is counted as a real weekend forecast. Full existing CI outcome must be checked before completion is asserted.
