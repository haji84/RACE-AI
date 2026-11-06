# Venue history to existing-model learning

> Native execution: implement inline with test-first changes and one final independent review. The user's existing implementation request authorizes this connection; production adoption remains prohibited.

**Goal:** Feed frozen venue/course observations and later official labels into the existing two-family shadow fitter, without rewriting old forecasts or inventing historical availability.

**Architecture:** Reuse `observed_weight_learning.fit_from_verified` and its feature equations, minimum 8 distinct races, training/holdout split and low-support coefficient guard. Read only independently admitted originals from the owner-encrypted canonical journal. Choose the latest input per race before filtering for the pinned venue dataset. Current all-period aggregates never enrich an already frozen input. Candidate/intake artifacts remain encrypted; public output contains counts only.

**Constraints:** No new model family, baseline coefficient changes, production promotion, external service, schedule, permissions or public private-data output. Unknown training rights cause HOLD, per the owner's original instruction. Existing source policy receives a distinct `model_training` purpose; analysis alone is insufficient. GitHub-created receipts remain distinct from artifact IDs (Git anchors have no artifact ID).

**Review focus:** Same-race duplicates cannot inflate samples; later non-venue P1 must not fall back to older P0; current dataset cannot backfill historical inputs; missing/expired purpose grants stop fitting; encrypted candidate corruption must fail and original journal must remain unchanged.

## Task 1 — checked learning intake and existing fitter
- [x] Add failing tests using invented bound snapshots: fit actual existing coefficients, preserve baselines, hold on rights, exclude absent/wrong dataset, latest-input semantics, missing-data/minimum-race guards.
- [x] Implement `race_ai/boat_venue_learning.py`: purpose gate, source bindings, counts and delegation to the existing fitter.
- [x] Run the focused learning/model tests.

## Task 2 — canonical journal and encrypted candidate
- [x] Test independent Git anchor admission, original preservation, encrypted roundtrip and tampering.
- [x] Add journal intake with real external receipt verification, no forged artifact IDs, immutable encrypted candidate output/readback and CLI.
- [x] Run locally on real G5: report actual eligible samples and HOLD conditions; never label a held candidate trained.

## Task 3 — existing Actions and acceptance
- [x] Add intake/verify and ciphertext/count-only upload steps to existing production readback job; no new workflow/job/schedule.
- [x] Run regression suite; independent review and finding resolution.
- [ ] Push only PR71 and confirm exact-code Actions (record run/HEAD in final handoff).
- [x] Record current rights-source URLs/SHA, actual versus synthetic results and sample deficits in `docs/BOAT_VENUE_LEARNING_CONNECTION_20261106.md`.

## Rulings

- The user authorized connecting learning, not bypassing third-party usage uncertainty or production approval. Provider pages checked this turn still do not explicitly admit model training; real fitting stays HOLD until a purpose-specific reviewed grant exists.
- The 7 million historical result rows are observations, not seven million verified pre-cutoff feature/label pairs. Do not reconstruct past forecast availability or lower the fitter's sample threshold to claim success.

## Verification ledger

- Test-first missing core, journal/crypto and CLI behaviors reproduced before implementing them. Holdout-mutation test exercises the actual optimizer and verifies unchanged fitted weights.
- Complete Python discovery: **1,888 tests, 98 skipped**, passed. Focused connection/fitter/permission suite: **41 passed** before final reporting fix.
- Real owner-key G5 restore and independent GitHub receipt recheck: **7 observed / 1 pinned venue input / 19 unapproved training sources**, `HOLD_MODEL_TRAINING_PERMISSION`; encrypted readback matched and source content SHA remained unchanged.
- One fresh whole-connection reviewer: **no Critical / Important findings**; 71 targeted tests passed independently. Minor finding: expired policy produced a generic error with no count artifact. Reproduced RED, changed to persisted permission-specific HOLD with no optimizer call, then **54 focused tests passed**.
- Reviewer exclusions ruled valid: provider legal sufficiency is still unconfirmed; reviewer did not independently rerun owner-key G5; accuracy improvement and production adoption remain unproven and prohibited. No such acceptance claim is made.
