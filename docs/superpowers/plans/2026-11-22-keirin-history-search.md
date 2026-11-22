# KEIRIN History Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find saved races across dates without scrolling through an unbounded date strip or thousands of cards.

**Architecture:** Extend the existing JS view/model; keep crypto/feed and prediction/scoring code unchanged. Generate the same app/style assets through the existing builder.

**Tech Stack:** Existing JavaScript, Node test runner, Python unittest/Playwright; no dependencies.

**Spec:** `docs/superpowers/specs/2026-11-22-keirin-history-search-design.md`

## Global Constraints

- Browser-only queries; no new public private-data index, source requests or services.
- Preserve every forecast/result revision and original budget/ticket behavior.
- Keep BOAT/study/model/source pins, workflow graph, permissions and production weights unchanged.
- No new PR or protected-main bypass. Prepare a concrete reviewed result before any necessary integration clarification.

## Review Focus

- `1R` must not match `11R`; full-width names/numbers and multiple terms work.
- Invalid/unavailable dates do not jump to a different race day.
- Pagination includes every match and keeps selections/budgets across pages.
- Refresh retains archive search state; day-specific accuracy denominators are not silently merged.
- Hundreds of dates and thousands of rows produce bounded navigation/cards without data loss.

### Task 1: Pure history selection and matching

**Files:** `web/keirin-note-model.js`, `tests/keirin_note_history.test.cjs`.

**Interfaces:** `historyRows(data,{period,day,from,to})`, `matchesHistory(row,{query,venue,raceNumber})`, `historyPage(rows,page,size=20)`.

- [x] Add real-behavior Node regressions for inclusive scopes, invalid dates, normalized AND queries, exact race numbers, and full traversal of 53 rows over three pages without mutating originals.
- [x] Observe the missing behavior fail; implement the three pure helpers and run focused tests. Nine RED failures became nine passes.

### Task 2: Scalable controls and rendering

**Files:** `web/keirin-note-view.js`, `web/keirin-note.css`, generated `web/app.js`, `web/style.css`; `tests/test_keirin_note_browser.py`.

- [x] Add failing browser regressions with hundreds of dates/2,000+ invented rows: calendar/range/all-period search, at most seven day buttons and twenty cards, previous/next traversal, reset, no-result range, selection/budget retention and background refresh. Five RED failures became passes.
- [x] Implement scope controls and pagination using Task1 helpers, preserving existing IDs and individual result/original rendering.
- [x] Add dates to multi-day cards; keep single-day summary semantics and hide those summaries for cross-day search.
- [x] Rebuild app/style with `python -m scripts.build_keirin_note_assets`; run full related Node/browser suites and existing page-delivery tests. Node150, Python53 and Chromium20 passed.

### Task 3: Review, concrete preview and delivery

- [x] Independently review the final diff and resolve findings with regressions. Three findings were reproduced before fixing: an empty calendar exposed an archive-wide unpaired-result section, a selected venue became invisible when the period changed, and different years had indistinguishable shortcut labels. Node150/Python53/Chromium23 passed after the fixes; no second review dispatch.
- [x] Exercise actual saved encrypted data privately at320/390/1440; publish only aggregate proof. All257 saved races traversed exactly once over13 pages; exact-date query57 and inclusive range114 at all three widths. Original/result history opens; no display-key/query transmission or provider request. Physical iPhone is not covered.
- [x] Preserve current main and the frozen accuracy worktree; push the reviewable `feat/keirin-history-search-20261122` UI branch and record remaining protected-main integration accurately. Source candidate3d61079f retains main ac444a33; only safe aggregate proof is included.
- [ ] Deliver through a legitimate existing PR path if available; otherwise ask for the minimum explicit exception after the implementation and review are ready. Related PRs are merged and remaining open PRs are unrelated/frozen; pending the owner's explicit exception for one normal PR. Main/Pages were not updated by this feature.
