# BOAT source readiness implementation plan

> For agentic workers: use superpowers:executing-plans task by task. Parent is the sole writer; a separate nonauthor reviews design and code.

**Goal:** Join existing PR64 preview evidence to the legacy PR71 readiness check without counting unusable observations as ready.

**Architecture:** Repair `build_readiness` and add an optional raw-preview join that delegates to the existing normalizer. Keep numeric candidates, temporal documentation and independent admission separate. No new predictor or external operation.

**Tech stack:** Existing Python 3.12 standard library, unittest, pinned PR64/71 references.

**Spec:** `docs/P0_BOAT_SOURCE_READINESS_CONTRACT_20261025.md`.

## Constraints and review focus

- Reuse clean isolated PR72 worktree starting at 2a99473; preserve other-writer audit and dirty original checkout.
- No new dependency, source fetch, cloud mutation, paid service, model inference, main merge or held33 retry.
- Reject bad identities, conflicting preview inputs, future data and inconsistent histories; test missing timestamps separately from numeric presence.
- Keep F/L, missing sample evidence and FULL75 gaps; do not backfill.
- Preserve all input objects and existing model APIs, coefficients and hashes.

## Task: repair the source join

Files: existing integration module/tests, contract document, this plan, taskboard. Add a CI path only if existing filters do not cover the repair.

- [x] Independent design criticism before implementation.
- [x] Write counterexample and canonical-preview tests; record expected RED.
- [x] Implement minimum validation/join/report changes; record GREEN.
- [x] Run reference-complete regression and separate independent code/adversarial review; repair important findings. Final local353 tests passed without failures/skips; independent38 targeted and25 adversarial cases passed after four reported gaps were repaired. Original RED and repair evidence remain in ignored artifacts and Issue68.
- [ ] Review exact diff; fresh remote and smoke guards; ordinary fast-forward push to existing PR72 only.
- [ ] Confirm exact-head CI, backup new evidence with byte/restore audit, update Issue68 and next dependency.
