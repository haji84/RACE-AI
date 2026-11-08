# Five Gates Live Acceptance Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans within each ownership domain and superpowers:dispatching-parallel-agents for independent domains.

**Goal:** verify the requested forecast, settlement, input, retention and PDCA paths with authenticated real data.
**Architecture:** reuse the existing source-free retained-audit Actions job and encrypted Git state. Keep the separately owned native source transaction fixed; append count-only verification rather than replacing model or financial logic.
**Tech Stack:** Python/unittest, Node, Playwright, existing AES-GCM/Git transport.
**Spec:** `docs/superpowers/specs/2026-11-07-boat-five-completion-design.md`, as renewed by the user's five-item request on 2026-11-08.

## Global Constraints

- GitHub only; no new task, workflow, job, schedule, permissions, provider, charge or bet.
- No shared native-branch push during the reviewed first-CI/issuer/source transaction.
- Keys and real private state stay in existing Actions; no local operator-file access.
- Preserve forecast clocks, originals, outcome journals, frozen allocation and retired-model history.
- Seller revival awaits the user's clarification; other work continues independently.

## Review Focus

- Budget inputs can change while displayed financial totals stay stale: compare actual figures for both budgets.
- Refunds and pending purchases must remain distinct from zero-valued losses.
- An unknown model's cutoff or input metric must remain unknown rather than be inferred.
- A restored Git snapshot must work without a live/expired artifact fetch or local file dependency.
- Historical descriptive gains must not become prospective improvement or promotion claims.

## Task 1: Numeric owner-site acceptance

Files: `scripts/boat_saved_site_context.py`, `scripts/boat_saved_site_check.cjs`, their existing tests, and a narrow Node helper if needed.
Consumes: authenticated selected-day feed and unchanged saved-performance calculation.
Produces: private bounded aggregate expectations and actual browser comparisons for day budgets 10000/5000 and race budgets 800/1000.

- [x] Reproduce the gap: the old checker verifies labels/input values, not financial equality.
- [x] Add failing stale-budget, wrong payout/refund/pending, and wrong-group cases.
- [x] Implement numeric matching without changing financial calculation or exposing picks.
- [ ] Verify local tests, independent review and actual three-width Actions browser.

## Task 2: Saved-data PDCA without a fitted-runtime dependency

Files: `scripts/boat_prospective_audit.py`, `scripts/saved_performance_report.cjs`, new `tests/test_saved_comparison_audit.py`.
Interface: `--saved-comparison-day YYYY-MM-DD --daily-budgets 10000,5000 --output <private path>` reads only authenticated selected-day saved data. Existing prospective-plan mode remains unchanged. Node CLI accepts the same optional daily-budget list; `report(view, options)` stays unchanged.

- [x] Test absent runtime/frozen plan, genuine Node aggregates, budgets, zero source access, privacy and no mutation; observe RED.
- [x] Implement the explicit descriptive mode, preserving false improvement/receipt/promotion flags.
- [x] Run new and existing Python/Node suites; obtain independent review.
- [ ] Run once in the existing guarded audit job and retain safe real-data counts.

## Task 3: Retention and environment-independent continuation

Files: existing vault/maintenance/control readers; a new narrow read-only verifier only if an actual acceptance gap is found.
Consumes: verified closed-worker metadata and encrypted retained ZIP/metadata/raw-source/control entries.
Produces: count-only independent-restore evidence or precise missing immutable references.

- [x] Separate prior implementation tests from actual last-worker retention evidence.
- [x] Select a Git-only independent restore path; no backfill writer or worker startup in a read-only proof.
- [ ] Verify fresh-runner bytes, source control/counter conservation and no live artifact fallback.
- [ ] Record continuation through the existing hourly coordinator and current native owner.

## Task 4: Remaining data and real forecast/PDCA acceptance

Files: existing source/evaluation operator plans and count-only evidence.

- [ ] Resolve seller scope from the pending user answer; never substitute fractions for rating points.
- [ ] Observe the canonical owner's remaining AUTO/KEIRIN data, actual model fits and restored model count.
- [ ] Integrate reviewed forecast-only publication at the owner's permitted boundary, after original retention/proof and before result work.
- [ ] Require current-day pre-cutoff originals and site visibility; retain later official result and matched comparison evidence.
- [ ] Report each gate from actual evidence; a valid PDCA conclusion may be no demonstrated improvement.

## Execution Ledger

- Baseline: isolated worktree at public `8a6c05e60af492b68b0c44e044dd15df750199dd`; shared native `7aa7ad24` has whole first CI success and is owned by the other active controller.
- Pre-flight: Tasks 1/2 share authenticated-view semantics but own disjoint files; Task 3 is read-only until its gap is established. Root alone owns workflow integration.
- Ruling: keep original prospective-plan mode intact and add an explicit descriptive mode; absence of a local fitted-runtime marker must not prevent an authenticated saved-data comparison.
- Ruling: user execution is already authorized; the only open question is seller scope, not permission to continue the other gates.
- Task 2 implementation verified: 16 Python tests and 29 Node tests passed; an independent review reran 16 Python and 6 report tests with no blocker. Literal 1R1000 cases preserve payout2400/refund1000/pending1000 while a 5000 daily budget buys5 races and a 10000 budget buys8. Real-data Actions execution remains pending.
- Task 3 review finding: authenticated GitHub metadata captures are not evidence of retained official result-source captures. Require the terminal worker's raw-capture inventory before claiming complete raw restoration.
- Task 3 implementation verified: 71 scoped retention/recovery/mirror tests passed; independent and root runs each passed the 16 new cases. Full status requires the terminal 7f locator and 11 unique official result receipts. Generic restoration remains explicitly partial. Actual fresh GitHub-runner proof is pending.
- Ruling: live acceptance uses the existing BOAT display job because it already has `contents:write` and `actions:read`; the daily result job does not have the artifact-read permission needed for closure maintenance. Reuse the isolated display branch and guard; do not increase permission scope. Keep the job's 20-minute limit and the source job's 360-minute limit.
- Task 1 implementation verified: explicit key-free Node child, bounded input, aggregate-only private context, exact group/day/generation and four-scenario DOM checks. Independent review is clear. Root combined verification passed 63 Python and 54 Node tests, including actual browser DOM with zero skips. Actual deployed-site numeric verification remains pending.
