# Existing Model Accuracy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Train and evaluate an original-preserving existing-A parameter candidate and remove an identified chronology leak without claiming unmeasured forward improvement.

**Architecture:** Pure offline research code consumes separately validated pre-race inputs and labels. The existing generator, settlement, registry, registered BOAT study and production weights remain unchanged. Private artifacts are encrypted with the existing display recipient; only safe aggregates are public.

**Tech Stack:** Python, unittest, NumPy/SciPy in an isolated research environment, existing P-256/HKDF/AES-GCM codec and GitHub.

**Spec:** `docs/superpowers/specs/2026-11-22-existing-model-accuracy-design.md`

## Global Constraints

- Preserve registered BOAT source1dbb47b68d487fc6def0bd4b10b1423f0a2145f6, witness, Nov19–24 window, all metrics and thresholds; no producer actions.
- No new model family/PR/workflow graph/charges/bets/production promotion. New research code makes no provider requests; ordinary existing main result acquisition is separately recorded. Never retrieve production state or RSA keys.
- No plaintext real snapshots, labels, weights or forecast originals in public Git/logs/artifacts.
- Do not alter the original A/B generator or settlement.

## Review Focus

- Cross-boundary as-of times cannot enter validation/test despite later cutoffs.
- Duplicate revisions and future/missing/held labels cannot inflate denominators.
- Candidate selection has no final-test-label argument and cannot change the artifact after locking.
- Baseline parameter ranking exactly matches existing A with ties and incomplete numeric features rejected.
- A later-created candidate replay is retrospective; only actually generated/saved still-future shadows may be described as pre-cutoff.

### Task 1: Chronology guard

**Files:** modify `race_ai/four_sport_learning.py`; create `tests/test_four_sport_learning_chronology.py`.

- [x] Add synthetic regressions rejecting validation as_of<=train_end and test as_of<=validation_end while admitting valid separated cohorts and preserving train-only coefficients.
- [x] Observe the rejection regressions fail before the fix.
- [x] Add the minimal lower-bound checks in `fit_chronological()` without changing the optimizer or train-only API.
- [x] Run focused regressions and existing relevant model suites; preserve actual red/green evidence.

### Task 2: Existing-A research candidate

**Files:** create `race_ai/keirin_existing_model_accuracy.py`; create `tests/test_keirin_existing_model_accuracy.py`.

**Interfaces:** validated private rows contain `snapshot`, `baseline`, `result` and immutable provenance. `fit_candidates(train_rows, validation_rows, ...)` has no test-label input. `rank_candidate(snapshot, artifact, generated_at, ticket_count=8)` preserves MODEL_A and actual clocks. Report fields distinguish research scope, retrospective diagnostics, source completeness and production=false.

- [x] Test exact baseline ticket parity for 5–9 starters/ties, input immutability, held labels, duplicates, split overlap, finite bounded weights, deterministic selection and generation after/too close to cutoff.
- [x] Observe feature tests fail before creating product code.
- [x] Implement source-based score components, bounded train-only coefficient fitting with a fixed regularization grid and independent validation selection including unchanged baseline.
- [x] Run tests and independently verify the same snapshot/result IDs and eight-ticket budgets.

### Task 3: Real evidence and encrypted forward shadow

**Files:** private data/artifact scripts outside Git; safe records under `docs/evidence/existing-model-accuracy-20261122/`; append `docs/RACE_AI_LATEST_STATUS.md`.

- [x] Read latest main/authentication and preserve existing work on an isolated branch.
- [x] Verify 53 encrypted packets; retain 145 research observations with exact original-runtime replay and original source hash, no float tolerance.
- [x] Build fixed historical baseline cohorts31/55; one training label is explicitly purged for availability, leaving30/55 without inspecting final-day results; record baseline scores and missing denominators.
- [x] Fit only historical training/validation and lock the candidate; use the unexamined final-day results only afterwards.
- [x] Generate remaining future shadows with actual times if candidate merits testing, encrypt and save them on the existing PR8 branch before their cutoffs; otherwise report no candidate improvement without fabricating one.
- [x] Independently read back ciphers and safe aggregate results; run final review/tests and preserve original model/study hashes.
- [ ] Update existing branch/PR8 records only; report measured changes and uncompleted forward support.

### Task 4: Read-only comparison of the frozen cohort

This concrete audit step was added once the actual candidate and 33 encrypted forecasts were frozen. It reuses the existing PDCA ticket/scoring functions, adds no registry authority and makes no provider requests.

- [x] Test unchanged candidate/cohort digests, same eight-ticket budgets, source/schema/clocks, duplicate revisions, pending/held results and private CLI output.
- [x] Reproduce and fix independent review findings about full-cohort binding and shadow metadata.
- [x] Apply the reviewed CLI to the actual authenticated Git package; publish only aggregate results.
- [x] Verify 742 configured and new tests, preserving the original A/B, workflow graph and BOAT study hashes.
- [ ] Demonstrate real forward accuracy improvement. Validation20/55 equals baseline; historical held-out15 has baseline7/candidate6; all33 sealed future forecasts await results at the recorded observation. Do not tune the frozen candidate using those labels.
