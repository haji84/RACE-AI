# Missing-aware measured experiments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task.

**Goal:** Keep useful research inference available with optional missing data and compare the same race at the same information stage.
**Architecture:** Add a separate pure measured pair-contrast adapter to the existing PL kernel; keep all old models unchanged. Join to strict source and same-stage comparison contracts on PR72.
**Tech Stack:** Python standard library, existing unittest, pinned existing GitHub CI.
**Spec:** docs/P0_BOAT_OBSERVED_PAIRWISE_20261027.md

## Global Constraints
No fabricated data, no odds/results input, no old output changes, no new cloud/paid resources.
Research outputs never claim formal pre-cutoff freeze or calibrated accuracy.
Root is sole Git writer. Builder owns new module/test only; other lane files remain unchanged.

## Review Focus
- Asymmetric missingness must be disclosed, with no per-lane reweighting.
- All-missing output must be labeled uninformative and separately counted.
- Callback mutation must not change the input whose hash is recorded.
- P0/P1 or revision/as-of mismatch must not be treated as paired comparison.
- Newer source gaps cannot be filled silently from older source revisions.

### Task1: Measured pair model
Files: race_ai/boat_observed_pairwise_models.py, tests/test_boat_observed_pairwise_models.py.
Interface: predict_pair(snapshot, *, allow_source=None) -> hashed research-only suite.
- [x] Write and run missing-feature/P0/complete-equivalence failing tests.
- [x] Implement exact schema, sources, transforms, two fixed contrast vectors, legacy PL, bounds, immutable hashes.
- [x] Exercise invalid sources/time/odds/callback mutation/F-L/all-missing and focused regressions.
- [x] Independent source review, repair important findings, rerun affected tests.

### Task2: Source and same-race comparison integration
PR72 paths: new measured source bridge and same-stage comparison module/tests;
reuse original ledger/result parser and existing private source/runtime boundaries.
- [x] Fix interfaces after reading current adapters; test rejection before implementation.
- [x] Execute source-to-candidate-to-same-result E2E offline on explicit synthetic data.
- [ ] Independently review bounded new real-source caller; one lawful new source inference.
- [x] Keep claimed timing, actual source parse, formal prospective proof and experiment metrics separate.

### Task3: Delivery
- [ ] Add focused paths to existing CI, run required local suites once per final change.
- [ ] Independent whole-change review; fresh both source-smoke manual-only checks, exact remote/local CAS.
- [ ] Commit/push only owned PR71/PR72 branches, verify automatic exact-head CI.
- [ ] Preserve original failure evidence and minimal new backup, record Issue68 and next unmet gates.
