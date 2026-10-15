# Reference UI Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this authorized UI lane inline.

**Goal:** Deliver the seven functional RACE AI views using the eight mobile/desktop references and only acquired or explicitly entered data.

**Architecture:** Retain the same-origin today feed, strict validation and safe DOM rendering. A small pure UI model owns manual tickets and recorded performance; app.js owns session state and view interactions; CSS owns desktop sidebar, mobile bottom navigation and responsive cards.

**Tech Stack:** Existing HTML/CSS/JavaScript, Python unittest, Node assertions, Playwright browser verification.

**Spec:** User's reference images and authorized UI brief, reflected in this plan.

## Global Constraints

- No web/api or backend changes, external writes, secrets, production release, or mocked real metrics.
- Preserve today contract, 6 MB cap, authorization/freshness/schema guards, same-origin fetch and textContent rendering.
- Budgets, manual candidates and purchase ledger remain session-only. Candidates are purchases only after an explicit record action.
- Unsupported AI grades, forecasts, odds, probabilities and payout estimates remain unacquired.

## Review Focus

- Unknown feed fields display 未取得 rather than numeric zero.
- Empty/error/stale feeds leave all pages usable with explicit status.
- Invalid lanes, duplicates, non-100-yen stakes and over-budget allocations reject clearly.
- Manual candidate entry never inflates actual expenditure or performance.
- Narrow phones contain wide data tables inside scroll regions and keep navigation usable.

### Task 1: Manual ticket model (8/16/24/32 point settings)

Files: web/ui-model.js; tests/test_ui_model.py; tests/ui_model.test.js.
Produces: RaceUI.validateTicket(lanes, amount), summarize(records), allocate(budget, count).
- [x] Write and run failing Node tests through Python unittest for ticket validation, allocation and settled-only performance.
- [x] Implement pure functions and run focused tests.

### Task 2: Responsive functional views

Files: web/index.html; web/app.js; web/style.css.
Consumes: RaceUI pure model and existing today schema.
- [x] Add browser assertions for navigation, missing data, search/detail, manual allocation/recording/settlement and responsive overflow.
- [x] Implement home/races/detail/picks/results/research/settings, responsive layout and accessible controls.
- [x] Verify syntax, full Python suite and browser interactions at desktop/mobile using a clearly marked test fixture only in test interception.
- [x] Inspect actual browser screenshots and commit locally.

## Execution record

Ruling: User explicitly requested normal implementation without further approvals; existing session scope authorizes this plan and inline execution. No additional approval gate.

Task 1 complete: model RED (missing module), GREEN; 32-point regression RED then GREEN.
Task 2 complete: real Chromium browser flows at 1440 desktop and 390/320 phones. Twenty-four selectable venues, explicit missing-venue state, all detail tabs, search/filtering, invalid lane rejection, candidate/purchase separation, allocation, manual recording/settlement, settings, stale/unapproved/future/hash refusal, and late file vs newer fetch regression verified. Browser screenshots inspected with local Japanese and symbol fonts. All fixture data are test-only intercepted responses whose racer names explicitly say 検証専用.
Review fixes: all venues remain selectable regardless of acquisition; absence is not interpreted as no event. Point limits are 8/16/24/32. Ticketwise accounting is labelled 買い目単位 and manual record returns are not AI performance. Both manual and auto input share current-day/authorization/time validation; async generation guards prevent an older read erasing newer data.
Ruling: budgets and manual ledger remain session-only per parent instruction; cost is losing unsaved records on refresh, disclosed in settings and picks.
Validation: python -m unittest discover -s tests => 162 tests, 1 existing JWT-dependency skip. Node syntax checks and git diff --check clean. Browser command: FONTCONFIG_PATH=/tmp/fonts RACE_UI_CHROMIUM_PACKAGE=<scratch @sparticuz/chromium package> node tests/ui_browser.test.js. Product repository has no new external dependencies.

Final independent review fixes: lowering the point limit preserves candidates and blocks recording until count fits; regression RED (record enabled) then GREEN. JST rollover invalidates yesterday's feed and blocks purchase; regression RED (3 old cards remained) then GREEN. Purchase records carry their JST day, today's budget uses only matching records, and session performance retains dated earlier records. Visible pages refresh the same-origin endpoint every 60 seconds; hidden pages skip refresh and returning visible refreshes immediately. A midnight timer clears prior-day data. Browser fake-clock assertions prove rollover and refresh counts.
