# Three-lane evidence integrity implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development for the separately owned A/B/C tasks; D is the sole integration writer. Steps use checkbox syntax for restart tracking.

**Goal:** Close three reproduced source/UI/model-settlement integration defects without promoting synthetic evidence to real acceptance.

**Architecture:** Reuse PR72 publication and proof-aware settlement, PR71 original model payloads and Safari odds audit. Keep source rights, immutable external time, official results, roster admission and actual iPhone verification as independent default-deny gates. Existing PR72 and PR71 remain authoritative; no new PR or wholesale merge.

**Tech Stack:** Existing Python standard library, Node built-ins, standard public GitHub-hosted runner. No installation, model download, source polling or cloud writes.

**Spec:** `docs/CODEX_RACE_AI_START_PROMPT_20261025.md`, master handoff, parallel runbook and #67/#68. Owner explicitly requested autonomous implementation of this supplied design; no replacement architecture is proposed.

## Global constraints

- No odds/popularity/result features, coefficient changes, >8 picks, fabricated publication/generation times, or exclusion of unforecast eligible races.
- No provider source requests, Access/credential changes, deployment, destructive storage operations, main merge or paid API in this unit.
- No CodeRabbit. Separate-context technical review does not establish independent GitHub APPROVED.
- Preserve held33/nonce, historical failures and original dirty root workspace.
- PR71/72 each have one writer: D; expected remote head must match and only normal fast-forward push is permitted.

## Design criticism and decisions

A reproduced equal-time and unchanged-SHA publication, plus capture-time-dependent duplicate identities. An explicit V2 stable identity must not silently reinterpret V1 issued hashes. B reproduced exported UI events failing the existing audit solely because per-event race identity is absent; add identity without weakening the audit. C reproduced hash-authenticated but independently supplied picks changing a score; derive picks from fully validated unchanged original model payloads, then reuse settlement independently per fixed model. Snapshot rights and model roster require independent admission; missing metadata cannot be fabricated from as_of. Horse source/model ID translation must preserve original bytes. See independent A/B/C design reports in the local evidence ledger.

## Review focus

- Legacy issued-event keys after restart: V1 ambiguity must hold, not silently re-enqueue.
- UI selection changes/error events: stale events cannot inherit the newly selected race ID.
- Rehashed forged model payload with old receipt: original external hash verification still denies it.
- Missing one model on one eligible race: same full denominator with zero hit.
- Callbacks mutate objects or return truthy non-bools: defensive snapshots/exact True, authority remains external.

### Task A: publication transition evidence and replay

Files: `race_ai/four_sport_publication_transition.py`, its tests and one transition contract document.

Consumes `inspect_presentation_observation`; produces explicitly versioned offline candidate event with stable sport/race/kind/sourceSHA/cutoff identity and separate capture evidence.

- [ ] Capture RED: equal timestamps, unchanged source SHA, repeated published bytes with later capture and stale PENDING must not enqueue.
- [ ] Implement minimal V2 identity/chronology/dedup with explicit V1 recovery limits. Keep all rights/model/monitor flags false.
- [ ] GREEN: existing four-sport/late/cross-race/cutoff/partial regressions plus new cases; independent reviewer checks migration semantics.

### Task B: Safari diagnostic identity

Files in separate PR71 worktree: `web/full-odds.js`, `workers/odds_preview_assets.mjs`, `tests/full_odds.test.cjs`.

Consumes actual current UI; produces metadata-only event export linked by each event's actual source race ID to unchanged `auditThreeCycles`.

- [ ] RED actual UI export -> existing audit, plus wrong/mixed/error race cases.
- [ ] Add per-event race ID and regenerate exact embedded assets; no UI audit relaxation or price/auth output.
- [ ] GREEN relevant UI/Worker/source/three-cycle tests, independent review and exact-head CI. Deployment/owner device remain separate.

### Task C: payload-bound multi-model settlement

Files: new `race_ai/model_suite_settlement.py`, tests, optional bounded synthetic cross-PR script.

`audit_model_settlements(ledger, results, deliveries, freezes, *, expected_model_ids, expected_model_versions=None, expected_model_source_sha40=None, validate_snapshot=None, allow_source=None, admit_model_roster=None, verify_result=None, verify_cutoff=None, verify_model_freeze=None, verify_coverage=None)`.

Ruling after independent review: model IDs alone do not predeclare algorithm versions. Require matching versions and a source pin before formal scores/freeze acceptance; roster admission receives full immutable ID/version/source-pin declarations. Missing declarations deny; these callbacks still do not authenticate actual producer execution. A reproduced rehashed undeclared-version replacement gets a negative regression before commit.

Additional inherited P0: PR71 horse diagnostic integer keys change JSON canonical order on persistence/reload. Keep original hashes and reject that serialized case; do not silently repair or rehash old records. Existing integration proves in-memory compatibility only. A versioned future canonicalization contract needs its own design review.

Use exact existing PR71 validator via injection, PR72 binding and settlement. Freeze metadata excludes picks; derive those from validated original model bytes. No model coefficients or execution changes. Source aliases remain separate from immutable model IDs.

- [ ] RED missing bridge, multiple models/same race, changed picks/original hash and wrong model receipts.
- [ ] Implement default-deny model roster/source/snapshot/receipt checks and per-model full denominator.
- [ ] GREEN missing models, revisions/refunds, horse aliases, defaults, forbidden fields, equal snapshots, and input immutability. Run pinned original PR71 models in synthetic integration separately.

### Task D: integrate evidence and verify

Files: `docs/ASSET_REUSE_MATRIX.md`, `docs/SPEC_CONFLICTS.md`, `docs/SRC_RIGHTS_STATUS.md`, `docs/REQUIRED_EXIT_GATES.md`, taskboard and offline workflow only as needed for exact pinned regression/integration.

- [x] Read live main/PR metadata and supplied documents; post initial ownership/blockers on #68.
- [x] Preserve baseline PR72 294 tests/13 missing-reference skips as historical evidence.
- [ ] Prepare pinned existing PR64/PR71 source references before full local/CI tests so missing checkout skips do not become false completion.
- [ ] Independent separate-context review of each final patch and fix concrete findings.
- [ ] Before each push, fresh both public-source-smoke manual-only check, existing deployment disabled configs and expected remote HEAD; lock one writer and normal push to existing branch.
- [ ] Read exact-head CI terminal logs; preserve any initial failures separately. Verify backups/restore and held33/root preservation.
- [ ] Update #68 with exact heads/runs/review and next concrete owner gate. Ask only for necessary scoped protected deployment/device operation after reviewable result exists.

This plan does not complete real-source rights, future external freeze, official settlement, iPhone acceptance, all-race operation or98% accuracy. Advance all safe local paths while those external gates remain blocked.
