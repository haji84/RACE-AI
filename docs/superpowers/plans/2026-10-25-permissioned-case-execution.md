# Permissioned single-case execution implementation plan

> For agentic workers: use the existing authorized C implementer and separate D reviewer; root alone integrates/pushes. No routine owner design checkpoint: owner explicitly authorized autonomous execution of the adopted design.

**Goal:** Implement the missing real-input preparation and read-only receipt callsites without changing original models or authorizing a source/write.

**Architecture:** Separate immutable one-case checkpoint; bounded exact-commit witness resolver. Reuse original PR71/72 delivery/codec/binding/receipt/settlement; leave synthetic journals unchanged.

**Tech stack:** Existing Python3.12/standard-library SQLite/unittest, pinned local reference; no new dependency.

**Spec:** docs/P0_PERMISSIONED_CASE_EXECUTION_20261025.md.

## Constraints and review focus

- Reuse clean owned PR72 worktree at45821b151af2536aea6545b16f89ffcd9cbddce0; preserve dirty root and all prior evidence.
- No source/cloud mutation, external write, new paid service, secret, schedule, main merge or held33 retry. Cost and device checks deferred.
- Distinguish real-capable code, fictional tests, stored real-source rejection and a successful prospective real E2E.
- Default-deny source/cutoff/roster/private-path admission; verify private_storage+private_derived, never fill missing required data.
- Foreign DB, competing first creation, crash before commit, post-cutoff commit and mutated request fail safely.
- Unknown write commit does no I/O; mismatched list/individual run/head/branch/server time/blob/canonical bytes cannot become a receipt.

## Task1 — root: bounded read-only witness resolution

Files: race_ai/github_witness_resolution.py; tests/test_github_witness_resolution.py.

- [ ] Write expected-failing tests for unknown commit, nominal exact3GET flow, malformed/truncated lists, ID/head/branch/time mismatch, extra/corrupt anchor, callback mutation and wrong verifier endpoints.
- [ ] Implement resolve_anchor_witness(prepared,commit_sha,persisted_at,*,expected_branch,github_fetch=None,trusted_legacy_verifier=None,clock=None), default denied, no writer or network default.
- [ ] Run RED/GREEN and independent adversarial review; preserve original failures.

## Task2 — C: private original-byte case preparation

Files: race_ai/permissioned_model_case.py; tests/test_permissioned_model_case.py.

- [ ] Finalize exact request/API and private-path/cutoff/storage requirements with separate D before implementation.
- [ ] TDD prepare_case/load_case, same-request replay, no foreign mutation, process crash/concurrency, missing permissions, typed original identity and no closed-race inference.
- [ ] Independently review code and actual saved-source admission boundary; repair important findings.

## Task3 — root integration and independent A/D QA

Files: a bounded offline integration script, existing offline workflow filters/step, source-rights/taskboard/asset documentation.

- [ ] Connect checkpoint→resolver→unchanged model settlement using authored fixtures; source/network defaults stay denied.
- [ ] Exercise new intake against already-retained actual records where lawful, retaining precise NO_FORECAST reasons; never relabel this as prospective success.
- [ ] Run relevant/full regression once after changes and reviews; normal FF push with fresh expected-head and both manual-only smoke guards.
- [ ] Confirm exact-head hosted CI; new-unit source/evidence backup and independent byte/restore audit; update Issue68 with exact remaining real-input dependencies.
