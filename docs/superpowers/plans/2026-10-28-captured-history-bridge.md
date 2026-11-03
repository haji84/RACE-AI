# Captured History Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect a measured single K day to existing pairwise research inputs and verify the real retained-data path.

**Architecture:** Add one pure adapter beside the existing B and publication-qualified K bridges. Reuse their validation; preserve original models and journals. Root alone integrates on existing PR72, expected starting HEAD 5608ab9c60c6ad48d3aa1978894f3215f4a9c1e9.

**Tech Stack:** Python standard library, unittest, existing pinned PR64/PR71 references.

**Spec:** docs/P0_CAPTURED_HISTORY_BRIDGE_20261028.md

## Global Constraints

- No source access, file writes, inference, training or forecast persistence occurs inside this adapter.
- Parser midnight stays a date sentinel; unknown publication remains null.
- All19 registry slots and the 15 unavailable model IDs stay visible.
- Original dirty worktree, held33, historical forecasts, source acquisitions and result failures stay unchanged.
- No model weight/ID/schema change, new dependency or paid/cloud/main/security change.

## Review Focus

- Duplicate or omitted source rows must not silently inflate or improve a mean.
- F/L/ABSENT and finish-unknown with numeric ST need separate truthful denominators.
- Source-day/UTC-offset and exact as-of boundaries must not admit target/future results.
- Malformed values or source identity collisions must not escape through the reused B bridge.
- New history must not be substituted into already sealed historical predictions.

### Task 1: Pure captured-history bridge

**Files:** Create race_ai/boat_captured_history_bridge.py and tests/test_boat_captured_history_bridge.py.

**Interfaces:** Consumes `build_program_snapshot` and existing K structural validation. Produces the exact function/return contract in the spec; downstream model receives only `result['snapshot']`.

- [ ] Write meaningful missing-API RED plus hand-calculated mean/count/lineage, mutation, empty/F/L/ABSENT, incomplete/duplicate/source/day/time/collision rejection tests. Catch the missing API as an assertion so RED is intentional.
- [ ] Run `python -m unittest discover -s tests -p test_boat_captured_history_bridge.py -v`; expected RED for the absent API.
- [ ] Implement the smallest pure adapter, preserving old modules and contracts.
- [ ] Run the same command; expected PASS. Add actual pinned-model integration coverage with explicit source-analysis callback, no source access or hidden network mocks.
- [ ] Independently review code and arithmetic. Fix important findings with retained RED-to-GREEN evidence.

### Task 2: Real retained-input evidence and integration

**Files:** Root owns this spec/plan, docs/CODEX_RACE_AI_PARALLEL_TASKBOARD_20261025.md, and existing offline-discovery workflow only if path filters/focused checks require it. Private evidence uses new artifacts/race41-* paths; never commit retained real facts or predictions.

**Interfaces:** Consumes Task1 API plus original Race39 K25/K26 normalized bytes. Produces a new private development replay/projection with exact input/code hashes, actual execution time, source0/model counts, and independent arithmetic checks. It is not an update to Race39/40 journals.

- [ ] Verify retained source hashes before replay; do not reacquire sources. Use a new explicit development context and preserve original capture clocks and old seals.
- [ ] Run independent stdlib arithmetic and source/participant/window checks; expected zero mismatch and no old-file modifications.
- [ ] Run reference-complete `python -m unittest discover -s tests -v` with existing Node runtime; expected all tests pass with no skip. Redirect full logs to private artifacts.
- [ ] Root commits only the reviewed allowed paths. Fresh-check both public-source-smoke branches remain manual-only, expected local/remote HEAD and held33; ordinary fast-forward push to existing PR72 only.
- [ ] Observe automatic Windows/Linux checks at the new exact head; never dispatch source jobs. Bind private evidence in a verified source/ZIP/restoration manifest and independent audit, then update Issue68/PR72 and next dependency.

Pre-flight: Task1 snapshot is the existing PR71 contract; Task2 must consume it without changing source timestamps or replaying old seals. Device/cost checks stay deferred as directly requested by Owner. Autonomous execution already authorized; no repeated plan-approval question is needed.
