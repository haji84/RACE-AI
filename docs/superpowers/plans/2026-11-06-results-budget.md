# Saved results and daily-budget simulation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline.

**Goal:** Show saved race results and Top8 matches, plus editable daily-budget hypothetical profit, on the existing private Pages link.

**Architecture:** Pure separate performance/accounting module feeds the existing UI without weakening official evidence gates. Accepted existing result artifacts append to a private copy. Stable view-only key/V2 authenticated view_id preserves the existing secret link.

**Tech Stack:** Existing vanilla UI/Node tests, Python SQLite/cryptography, GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-11-06-results-budget-design.md`

## Global Constraints

- GitHub only, no main merge, paid services, access/Actions permission changes, root key export, live-worker changes, plaintext public originals or actual bets.
- Preserve exact original predictions, captured result history, model/stage/version/variant identity, latest pending observations, and all official evaluation gates.
- Daily budget starts at10,000 yen and is editable in100-yen units. Eight100-yen tickets per eligible saved Top8; deterministic cutoff order; no partial plan and no reinvestment; daily reset.
- Hypothetical results and money remain separate from actual purchases and formal accuracy claims.

## Review Focus

- Unknown results or unknown winning payouts cannot be converted to losses/zero money.
- Post-result filtering, refund reuse, mixed variants or multi-day selection cannot change the declared strategy.
- Multiple winning combinations and partial refunds cannot double count payouts; reject unsafe totals or unsupported refund attribution.
- Existing old secret links must decrypt only their authenticated view lineage; no public key/secret leakage or root-key substitution.
- Code/branch success is separate from actual deployed results/budget UI and data freshness.

### Task 1: Pure comparison and daily-budget accounting

Create `web/saved-performance.js`, `tests/saved_performance.test.cjs`. Interfaces: `compare(row,prediction)`, `simulate(records,group,dailyBudget)` return immutable derived statuses, per-race ledger, daily and aggregate money/count summaries.

- [x] Write RED tests for Top8 match/miss/wait/no forecast, daily10k→12 whole plans/9,600 spend/400 reserve, editable budgets, later-day reset, deterministic cutoff ties, result-independent selection, missing payout, void/partial refund/dead heat, overflow and unchanged input.
- [x] Implement minimal pure functions; GREEN focused Node tests; commit.

### Task 2: Visible results and editable budget

Modify `web/index.html`, `app.js`, `style.css`; wire the asset through existing server/offline/Pages allowlists; extend existing browser/CI tests. Results page shows complete ledger, model selection and date/observation coverage; separate scenario metrics and 4-condition table; cards/details show derived outcome.

- [x] Browser RED for real-like result visibility, pending rows, changed budget recalculation, model isolation, official metrics unchanged, no actual purchase or key transmission and mobile/desktop fit.
- [x] Implement minimal UI/wiring; GREEN new and existing UI regressions; commit.

### Task 3: Existing results and stable private link deployment

Modify `race_ai/saved_pages.py`, `web/saved-view-crypto.js`, CLI/tests for optional private viewer reuse and V2 authenticated view_id, preserving V1. Reuse the existing completed worker artifact only after GitHub metadata/digest/CRC and exact result identity checks, append revisions to a private copy without rewriting originals.

- [x] RED→GREEN for original V1 link + updated V2 payload, wrong view/key/hash/AAD, private key mode and publication bounds.
- [x] Fresh independent review; fix confirmed Important/Critical findings before actual update.
- [x] Verify all624 original forecasts, accepted result counts and hypothetical money independently; publish code to existing PR71, preserve concurrent changes, full CI.
- [x] Publish reviewed encrypted Pages update under expected parent; verify original owner URL, actual result/money controls and served hashes; report cause/fix and data coverage.

## Completed validation

- Source implementation: `204cc2b`, included in tested descendant `006bbfdc40c1fc511429e1f1c45ea5d2b4184709`. Existing PR71 CI run `42170868715` succeeded, including1,869 Python discovery tests,251 isolated video tests and all financial/browser contracts. AUTORACE run `42170868654` also succeeded.
- Private readback: all624 original predictions across156 races unchanged;30 final results displayed;126 races remain pending or unavailable. Eight independent money scenarios and both390/1440 viewports passed.
- GitHub Pages update: `9dfd704016e4199942c11a064f400f738ae13eea`. Every served file SHA and the original owner URL were verified against the reviewed encrypted bundle. Live result tables, all4 condition selections,10,000→5,000 budget changes, original Top8 and reload passed without transmitting or storing the view key. No worker, original checkpoint key, model or actual purchase was changed.
- Private validation records remain outside Git. The site represents the saved snapshot, not a claim of continuous live result delivery.
