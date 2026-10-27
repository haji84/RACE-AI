# Fair model evaluation implementation plan

> Execute continuously under the owner's accepted evaluation approach. Use test-driven implementation and independent review; no repeated approval of the agreed design.

**Goal:** Compare the frozen model roster on the same races and information cutoffs, preserve missing forecasts, and separate development, tuning and untouched final evaluation.

**Architecture:** Reuse the existing model engines, B/K readers, feature adapters and fingerprint witness. Add an offline experiment contract and create-only local evaluation journal. Training receives training labels only. Final evaluation reads labels only after the experiment and predictions are sealed; historical reconstruction and independently witnessed prospective forecasts remain different evidence classes.

**Tech stack:** Python standard library, existing unittest/Actions gates; existing GitHub hash-only witness. No new service or recurring source job.

**Spec:** Owner's 2026-10-27 accepted same-race/same-condition evaluation request; Issue #67/#68; AGENTS.md.

## Constraints and ownership

- Original checkout and held 33 predictions remain unchanged; existing PRs #71/#72 are reused.
- Root owns PR72 experiment contract/journal, tests, documentation and integration. PR71 learning author owns only training-only entrypoint and its tests. Today caller author owns private `artifacts/race39-today-*`. Independent reviewer writes review evidence only.
- Root is the only commit/push writer. Expected heads: PR71 `98e525478d598f6e56bcb6b5fc7006dbf893d2fe`, PR72 `b9294a3e9c06cc5de92c9ca9c26bb00ef008d1c6`.
- No invented values, source publication times, sample denominators or historical creation times. No odds/results enter inference. No automatic wagers, new paid services, deployment or main merge.
- Oct15–17 results already inspected are development/replay evidence. A new model cannot call them untouched final tests. Today captures use actual current clocks and remaining cutoffs.
- Source access is bounded, admitted and independently reviewed before execution. New B27 observation must preserve the old successful attempt and explicitly correct its missing private input/prediction retention. Failed K reads are not blindly retried.

## Review focus

1. Final labels leaking through a training diagnostic or artifact hash.
2. A model changing the race set or information timestamp to improve its reported rate.
3. Unknown results, blocked forecasts and closed races disappearing from denominators.
4. Reopening final results under a new experiment ID or after a crash.
5. A local clock/hash falsely promoted to independent pre-cutoff evidence.

## Tasks

- [x] PR72 `race_ai/evaluation_experiment.py`, `tests/test_evaluation_experiment.py`: validate fixed roster/code/artifact hashes, chronological splits, same-context input identity and complete race/model/stage rows. Score labels only after a prediction seal; retain unknown/excluded/blocked counts and fixed common-cohort comparisons. Reject leakage and bad chronology. Tests use independently derived small counts.
- [x] PR72 `race_ai/evaluation_journal.py`, `tests/test_evaluation_journal.py`: create-only plan/predictions, hash readback, cross-experiment final-race consumption, reserve-before-label-reader, crash/restart and concurrent rejection. Local journal does not establish external authority.
- [x] PR71 `race_ai/four_sport_learning.py`, `tests/test_four_sport_train_only.py`: add a train-only API reusing existing gradients/vectors; refuse validation/test rows, create artifact without test metrics, bind real creation time, preserve legacy behavior.
- [ ] Private data lane: inventory reusable historical facts and missing model fields; normalize lawful new K facts with observed time and individual source hashes; never substitute K counts for B's differently defined aggregates.
- [ ] Today lane: predeclare all discovered races and 19 model statuses, retain actual input/full candidates/Top8 before results, then obtain existing independent hash witness before each eligible cutoff. Failed/missed cases remain explicit. Official results join only after their actual publication/cutoff.
- [ ] Run focused tests and necessary existing regression, independent review, exact-head CI for the changed branches, private artifact backup/readback and update Issue #68 with measured evidence and outstanding gaps.

## Execution ledger

- Initial existing heads/checks read. Original checkout dirty nine entries preserved. Previous Race38 409-race replay and backup are reused, not rerun.
- Design review identified legacy `fit_chronological` returning test metrics during fitting and legacy market-implied feature support. The new train-only entrypoint excludes test feedback; the legacy market-bearing artifact remains inadmissible.
- Model/data gaps remain real: B+K cannot supply every existing model's weather, style, full feature semantics or trained artifacts. Missing models must remain visible rather than get fabricated inputs.

- Train-only PR71 head `6f75fa9f98beb5a6d8f190694e96695d5ffb31be`: exact-head Windows/Linux and viewer CI run40442057767 succeeded. Local49 four-sport tests and independent20 probes passed. No main merge.
- New generic evaluator final focused48 tests passed; the prior full677-test regression passed before the subsequent huge-integer error-normalization regression was added. Exact pushed-head CI is a separate evidence step.
- B27:168 discovered races,131 locally timely forecasts per each of four engines,524 predictions; all19 statuses retained. GitHub run40440865560 witnessed the whole seal before130 planned cutoffs and afterone.
- K25/K26:310 complete races/1860 rows, one incomplete race quarantined, actual capture later than those forecasts. No5-sample complete histories or FULL75-ready races were established.
- First three-race result batch: one normal result (allfour actual forecasts missed), one pending and one unavailable/invalid; all57 slots retained. Six total source GET attempts across B/K/results, no retry.
- All-model execution and final accuracy remain incomplete. Private real collectors and the new generic CLI are different paths; a reviewed retained-case connection and additional eligible source facts are still required.
