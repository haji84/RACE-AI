# KEIRIN official A/B automation implementation plan

**Goal:** Connect the existing nationwide A/B pipeline to verified official schedules and results, preserve immutable forecasts, and produce an honest owner-readable outcome report.

**Architecture:** Keep the existing A/B generator, RSA/AES envelopes, same-repository Git state and paired scorer. Add a bounded HTTPS adapter for the public JSON actually used by KEIRIN.JP, a server-timestamp origin verifier, and one orchestration CLI. The existing workflow remains the scheduler.

**Tech stack:** Python 3.11+, unittest, cryptography, BeautifulSoup, Git, GitHub Actions.

**Spec:** `docs/KEIRIN_ALL_RACES_AUTOGEN_AND_AUTO_SETTLE_HANDOFF_20261119.md`, current owner request to identify and complete all remaining work, and `AGENTS.md`.

## Global constraints

- No Cloudflare, Vercel, paid provider, new repository, wagering, or security-permission change.
- Use the existing owner RSA key and `RACE_AI_KEIRIN_PRIVATE_RSA_PEM`; never expose private keys, plaintext forecasts, raw source documents or SQLite in public Git, logs or artifacts.
- Preserve the registered full-day denominator and all original/revision history. Missing forecasts are not misses.
- A/B is mandatory; C and the abandoned four-model parent are not prerequisites.
- A forecast and its independently restored server-timestamped evidence must precede the official cutoff by at least 65 seconds.
- CI, registration, decryption and real scoring are different acceptance facts.
- Do not merge unrelated Draft research or weaken protected-main requirements.

## Review focus

- Provider denial after the first successful page must stop every subsequent GET, including after midnight and when stop persistence fails.
- Early expired races and missing fields must not starve future races behind a fixed batch.
- Same URL with changed official data must create a new revision; conflicting race/date/venue data must remain unscored.
- Git author dates and an unsigned local receipt must not be accepted as independent pre-cutoff proof.
- Valid variable ticket counts, refunds, ties and missing races must preserve the paired A/B denominator and correct hypothetical stakes.

## Tasks and ownership

### 1. Official public source adapter

- Add `race_ai/keirin_official_public_source.py` and `tests/test_keirin_official_public_source.py`.
- Inspect official HTML/JavaScript and actual JSON before encoding any endpoint or field.
- `fetch_day_schedule(day_jst, fetcher=None, clock=None)` returns all official venue/race snapshots and literal cutoff/start times.
- `fetch_race_result(race_id, schedule=None, fetcher=None, clock=None, previous_result=None)` returns the canonical existing scorer contract plus byte-bound source provenance.
- Verify synthetic identity, duplicate, incomplete, pending, refund/tie and provider-denial cases; then read actual 2026-11-18/19 data with safe counts only.

### 2. Capture progress and provider stop

- Fix `scripts/keirin_github_only_ab_day.py`, `scripts/keirin_github_only_result_day.py` and `race_ai/keirin_github_provider_stop.py` with their targeted tests.
- Filter expired verified hints and order imminent races before applying the request budget. Unknown-hint fallback must not permanently repeat the first batch.
- Scope source stops to observed JST day and latch before persistence, so a failed state write cannot allow further source GETs.

### 3. Original authentication and scorer correctness

- Fix variable-cap replay in `race_ai/keirin_nationwide_auto_settlement.py` and its tests.
- Add `race_ai/keirin_github_origin_evidence.py` and tests binding archive ZIP digests, forecast SHA, trusted repository/workflow/run/job identities and GitHub server timestamps.
- Accept only distinct successful producer/readback jobs with pre-cutoff evidence; do not use Git commit clocks as proof.
- Preserve HOLD for any cancellation/refund structure that has not actually been supported and verified; do not manufacture a normal result.

### 4. Executable official pipeline and encrypted result history

- Add `scripts/keirin_official_day_pipeline.py` and targeted integration tests.
- Reconcile the official full-day cohort with source-linked secondary URLs, injecting literal official cutoff hints while retaining missing races in the denominator.
- Restore exact Git ciphertext, collect official result revisions, fetch independent origin evidence, use the existing RSA key and scorer, and output aggregate-safe reports.
- Persist encrypted source/result evidence and redacted paired score receipts with create-once Git semantics; preserve correction history.
- Wire capture/readback/results sequentially into the existing nationwide workflow, with temporary-file cleanup on all exits.

### 5. Owner review and acceptance

- Provide an owner-only report showing generated/scored/HOLD/refund states distinctly and A/B on the same races; use an encrypted viewer when a public transport is required.
- Reproduce one actual saved pre-cutoff A/B original against genuine official results, with a safe reproducible evidence receipt.
- Run the relevant repository test suite and inspect exact-head Actions evidence.
- Review the scoped diff independently, check production prerequisites without changing permissions, and keep any missing live prerequisite explicitly open.

## Initial evidence and decisions

- Initial exact head: `c26061cdb75bfe3b772be20f43fae1628c23998a`; local baseline 114 relevant tests passed.
- Confirmed missing wiring: the current result job only records secondary consensus and hard-codes official scored count to zero.
- Confirmed defects under independent reproduction: batch starvation, race-day rather than observation-day stops, swallowed stop-persistence errors, and variable-ticket replay using a fixed default cap.
- Official JSON endpoints are being derived from KEIRIN.JP's actual linked JavaScript, not guessed or copied from third-party endpoint lists.
- Existing research PR is retained. Production integration is assessed separately against the latest main; the large historical Draft is not an automatic merge candidate.

## Implemented outcome and acceptance boundary

- The five implementation tasks are connected in executable code: official source parsing, fair capture with persisted selection progress, actual GitHub origin verification, RSA/AES original replay and settlement, encrypted revision history, and the owner report/offline viewer.
- Independent review found and closed correction rollback after HOLD, result/capture/origin queue starvation, mixed venue replacement shrinking the cohort, byte reconstruction, partial-rerun job discovery, cross-midnight refusal reuse, and cursor-only evidence-history growth.
- Scheduling counters now occupy a small mutable Git metadata file whose prior versions remain in Git history. Actual source/result revisions remain immutable.
- Actual historical acceptance: Utsunomiya 202611182401, true saved original and server metadata/ZIPs, existing owner RSA authentication and original model replay, official source reparse and cutoff. A12/B8 both missed; 1 pair scored in the 79-R cohort. No source GET was needed for final replay.
- Production is not declared complete: the official robots policy excludes the JSON route from its Allow rules, new source collection is disabled, some secondary access fails, actual refund shapes remain held, existing Secret availability and protected-main deployment are unverified, and no future full nationwide day has completed this new workflow.
- Full status and evidence boundaries are recorded in `docs/KEIRIN_OFFICIAL_AUTOMATION_COMPLETION_AUDIT_20261119.md`. A local/CI pass cannot substitute for its remaining operational gates.
