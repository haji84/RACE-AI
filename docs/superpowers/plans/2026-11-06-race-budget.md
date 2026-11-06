# Per-race1,000-yen simulation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline.

**Goal:** Compare800-yen Top8 staking with1,000-yen capped support-based reference allocation on the existing private site.

**Architecture:** Extend the pure accounting module with allocation evidence and weighted ticket settlement. Keep original comparison separate; reuse the existing encrypted snapshot and publication path.

**Tech Stack:** Existing vanilla JS, Node/Playwright, Python SQLite/AES-GCM, GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-11-06-race-budget-design.md`

## Global Constraints

- GitHub only; preserve originals, model/stage identity, official gates, manual purchases, workers and keys.
- Default800-yen behavior unchanged; selectable1,000-yen cap, base8×100 and200-yen support-based additions.
- Support is an unvalidated reference indicator, not calibrated confidence. No post-result or future-saved peer selection, rank-based tie break or invented odds/longshot claims.
- Daily cap reserves800/1,000 per funded race; unused additions stay unspent; never reinvest returns.

## Review Focus

- Multiply refunds and payouts by actual units, including dead heats; reject unsafe arithmetic.
- Do not count correlated variants as independent families or admit late/different-stage/missing-clock peers.
- Missing support must leave200 unallocated, rather than silently topping the first prediction.
- Daily plan count, settled count and pending money cannot keep hard-coded800 divisors.
- Budget/model changes, no forecast, unsafe imports and private reload must preserve existing behavior.

### Task1: Allocation and weighted accounting

Files: `web/saved-performance.js`, `tests/saved_performance.test.cjs`.

Interface: `allocate(row,prediction,raceBudget=800)` returns weighted tickets/evidence/held amount; `simulate(records,group,dailyBudget,{raceBudget=800}={})` returns reserved/held/spent/settled count and per-race plans.

- [x] RED tests for1,000 cap→10 races, non-rank allocation, weighted payouts/partial/full refunds/dead heat, absent or future/duplicate evidence, daily reset, overflow and immutable originals.
- [x] Implement and GREEN financial regression; commit.

### Task2: Comparison UI and original-link delivery

Files: `web/index.html`, `web/app.js`, `tests/results_budget_browser.test.js`, `docs/BOAT_SAVED_PAGES.md`.

- [x] RED browser assertions for800/1,000 switch, daily cap, reference evidence and held amount; implement and GREEN390/1440.
- [ ] Fresh read-only review; resolve Critical/Important issues.
- [ ] Independently verify the same624 originals and weighted real-data money, update existing PR preserving concurrent work, publish encrypted snapshot with exact parent, verify served hashes and original URL.
