# Official KEIRIN Source Connection Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans or subagent-driven-development. Track each check below.

**Goal:** Obtain source-backed partial KEIRIN input through the ordinary official SP route, eliminating the hardcoded denied WINTICKET dependency from default owner collection.

**Architecture:** Reuse reviewed calendar/SP parsers in a guarded ordinary browser collector. Map its sanitized result into the existing owner-collection report and retain all complete-input/model gates.

**Tech Stack:** Python, existing Playwright 1.56.0 Chromium, unittest, existing GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-19-keirin-official-source-connection.md`.

## Global Constraints

No new PR/model/service/charge/UI deployment/bet/weight switch. No workflow/job/step/input/cron/runner/timeout/permission/marker definitions. No credentials or owner keys outside Actions. No retries, UA/headers/cookie/network tricks. Source/model admission remains false for partial inputs.

## Review Focus

- A denied subresource must stop later source navigation.
- Request counters distinguish transmitted unknown outcomes from blocked-before-send.
- A changed DOM token or selected date/venue/race must reject before POST.
- Private raw source must never appear in returned report/stdout/public files.
- Pinned-source namespace imports must find new readers without replacing model modules.

### Task 1: Ordinary official browser collector

**Files:** create `race_ai/keirin_official_sp_browser.py`, `tests/test_keirin_official_sp_browser.py`.

**Interface:** `collect_official_sp(inbox, *, clock=None, monotonic=None, budget_seconds=240, browser_factory=None)` returns the spec's sanitized count-only report. Lazy-load Playwright so public offline tests require no installed browser.

- [ ] Write and run failing invented tests for exact public POST guards, denial/unknown status, token/scope changes, private output, and budget-prefix accounting.
- [ ] Implement serial normal DOM navigation and use the existing raw-byte parsers. Preserve raw receipts privately and all admission holds.
- [ ] Run targeted tests without external network; compare saved real source parsing privately.

### Task 2: Existing owner collector and workflow connection

**Files:** modify `scripts/keirin_cloud_owner_inputs.py`, its tests, and existing `.github/workflows/keirin-pr71-owner-autonomous.yml` run bodies only.

- [ ] Write failing tests proving default owner collection calls official transport and never the denied legacy source; explicit injected legacy tests retain their contract.
- [ ] Implement the default partial-source mapping and safe pinned-namespace imports. Licensed-source precedence, zero model admission and no empty generation remain unchanged.
- [ ] Reuse existing run steps to install the existing Playwright version/browser and run the added public offline tests; preserve every workflow definition and source pin.
- [ ] Run related owner/cycle/workflow tests and compare workflow structure to the original.

### Task 3: Review and actual acquisition

- [ ] Independently review transport, source selection, privacy and workflow invariants; fix concrete failures.
- [ ] Preserve original existing-PR head and changes in ancestry; normal FF update only, no new PR or forced push.
- [ ] Complete required CI and protected integration, then inspect actual trusted completed-job logs for HTTP statuses and parsed counts. Do not equate a green wrapper with successful collection or full prediction.
- [ ] Save source-safe evidence and latest status, explicitly distinguishing an operational official-source path from a WINTICKET-side unblock.
