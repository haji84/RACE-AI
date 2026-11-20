# KEIRIN live result implementation plan

> **For agentic workers:** Use the approved task decomposition below; independent changes are reviewed together before publication.

**Goal:** Persist safe failure diagnostics and automatically publish admitted results to the existing encrypted owner view.

**Architecture:** Repair official collection first, build a bounded callback observer, publish strictly validated result-only encrypted packets, and incrementally refresh the existing viewer. Existing access stops and production admission remain authoritative.

**Tech Stack:** Python unittest, existing cryptography/BeautifulSoup, JavaScript Node tests, GitHub Actions and Git state.

**Spec:** `docs/superpowers/specs/2026-11-21-keirin-live-results-design.md`.

## Global constraints

- GitHub only; no new keys, permissions or services.
- No real provider retry while the unresolved stop is latched.
- No plaintext source documents, forecasts or private capabilities in public state.
- Keep all frozen originals and revisions; do not change prediction weights.

## Review focus

- HTTP 200 ordinary reCAPTCHA script versus a real blocking page.
- A payout-guide refusal after a valid result must retain that result and stop subsequent requests.
- Secondary matching results must never gain official or monetary-scored status.
- A feed refresh, correction or failed refresh must preserve all user selections and immutable forecast originals.
- A prior denial, clock bound or publication error must not cause source retries or silently unlatched collection.

## Tasks

- [x] Collector: reproduce diagnostic loss and challenge false positive, then add allowlisted diagnostics and independent order/unit capture with meaningful red/green tests.
- [x] Observer: test and implement bounded 60-second ticks, immediate publication, deduplication, and stop-before-request behavior.
- [x] Producer: validate official raw source lineage; build result-only packets; seal to the existing owner recipient and read back immutable Git entries.
- [x] Viewer: validate incremental feed lineage; apply result overlays; refresh every 30 seconds while visible and preserve selections and independent arms.
- [x] Workflow: replace one-shot result execution with the guarded observer; retain secret isolation, safe diagnostics artifacts and plaintext cleanup.
- [ ] Verify the integrated relevant suites and an independent branch review, publish the reviewed change through existing GitHub checks, and report real-live limitations honestly.
