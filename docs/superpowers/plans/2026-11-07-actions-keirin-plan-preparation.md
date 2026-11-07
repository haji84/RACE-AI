# Actions-only KEIRIN Plan Preparation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare unchanged KEIRIN16/32 plans with the Actions owner secret, without issuing authority or using a local key.

**Architecture:** A new preparation core/CLI authenticates a fully tested code parent and the actual previous source. The existing issuer job adds a literal preparation route; its old issue branch and writer remain unchanged.

**Tech Stack:** Python, existing AES/MAC/native/result readers, existing GitHub transport, GitHub Actions YAML.

**Spec:** `docs/superpowers/specs/2026-11-07-actions-keirin-plan-preparation-design.md`

## Global Constraints

- Isolated worktree only; no actual key, provider, GitHub write, public request, capsule or model operation.
- Existing issue guards/writer/defaults unchanged; no workflow/job/schedule/permission additions.
- Code parent full immutable attempt1 proof precedes key; current attempt2 allowed only for the exact previous source.
- Exact three output names: sealedplan.enc, request.json, counts.json; plan-only round900033.
- All original native/pins/clocks/terms/static bytes preserved; old UNKNOWN null/32 remains.

## Review Focus

- An unverified code parent must never reach the owner key loader.
- A newer uncertain/denied public issue must prevent selecting an older successful source.
- Artifact metadata, source owner MAC and actual normal result must join exact raw/capsule/native bytes.
- Case selection must use original order and actual7/9 roster, never outcome/amount preference.
- Ready/HOLD output must never expose raw source, key, plaintext plan, extra files or a writer call.

### Task 1: Pure context and deterministic plan/request builder

Files: new `race_ai/all_existing_model_official_prepare.py`; new `tests/test_official_result_prepare.py`.

- [x] Write schema/context and deterministic selection tests, run RED.
- [x] Implement literal schemas, full-parent/source scope and original-case selection.
- [x] Run focused tests GREEN, including current-parent attempt1 and exact-source attempt2.

### Task 2: Authenticated source-free preparation CLI

Files: new `scripts/all_existing_model_official_result_prepare.py`; new `tests/test_official_result_prepare_actions.py`.

- [x] Write real fixture/MAC and early-key/output/privacy tests, run RED.
- [x] Reuse existing read-only transport, original capsule/journal/native/result readers and round900033 sealing.
- [x] Prove native membership, all prior closure, both KEIRIN kinds, source0/writer0 and exact outputs.

### Task 3: Existing issuer-job route

Files: `.github/workflows/forecast-audit-ui.yml`; new `tests/test_official_result_prepare_workflow.py`.

- [x] Write workflow shell/gate/output tests, run RED.
- [x] Add prep-only prefix/step/artifact routing in the existing job; preserve old issue behavior.
- [x] Run new tests and existing issuer workflow/permission tests, verify shell syntax.

### Task 4: Verification and independent review

- [x] Run all new tests plus existing issue/continuation/probe/historical neighbors.
- [x] Independently review core/CLI and job/privacy boundaries; fix concrete findings with RED→GREEN.
- [x] Commit locally only, report exact SHA/tests/remaining actual-operation gates to root.
