# Name-bound result label implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax.

**Goal:** Join a newly obtained official result to an exact frozen alias-bound forecast and evaluate its three phases without changing legacy data.

**Architecture:** Separate pure label packet and one-source worker; separate finalized private store/API; bounded existing-OIDC caller/manual workflow. Evaluation consumes the validated separate label first and preserves legacy schema1 fallback only when truly absent.

**Tech Stack:** Existing Python3.12/standard library, current parser/SQLite memory/Blob helpers, signed GitHub OIDC and protected Vercel Preview; no new dependency.

**Spec:** docs/superpowers/specs/2026-10-15-name-bound-result.md

## Global Constraints

- Owner-selected cwd/branch codex/race-ai-completion; never main/Production, no new secrets/trust scope or auth changes.
- Original B names, all118 baselines, completed3/4/7 proof/numeric/4result/v1/media evidence stay immutable. No real source requests by implementers/reviewers.
- Current same-JST actual aware clocks, postclose independent labels; no backdating, prefix matching, raw HTML/media/keys/ephemeral URL retention.
- MAX_BYTES=256000; official HTML timeout10/max1000000/one attempt; caller240s/5GET/1POST/1official. UNVALIDATED/skip/[] always.
- Use exact fields/constants/signatures in the spec. Sequential implementation, test-first, one full suite before own commit, no subagents inside worker/reviewer.

## Review Focus

- Independent proof borrowed from a different race or regenerated hash-only forgery must fail (Task1).
- GET absence caused by authentication/transport/store error must not trigger official acquisition (Task3).
- Late write/readback/finalclose or JST midnight must never leave COMPLETED/adopted invalid evidence (Tasks2/3).
- Supplied malformed separate label must fail rather than use a valid legacy fallback (Task2).
- Canonical numeric/bool/hash/nonce lookalikes, partial/orphan saved packets and replaced/symlink final manifests must fail safely (Tasks1/2/3).

### Task 1: Pure label identity and one-source worker

**Files:** Create web/name_bound_result.py; race_ai/name_bound_result_source.py; tests/test_name_bound_result.py; tests/test_name_bound_result_source.py.

**Interfaces:** Produces result_context, build_name_bound_result, validate_name_bound_result, validate_name_bound_result_envelope, result_bundle and collect_name_bound_result with exact signatures/schemas/statuses in spec. Consumes finalized forecast and its own baseline/name proof; projected race only validates strict parser. No store/API edits.

- [ ] Write tests first: real synthetic full-name result with B abbreviation rejected by legacy validation yet accepted by own independent projected proof; deep-copy immutability and full SHA/link/clock replay. Mutate all parent/race/registration/name/hash/status/flag/nonce/schema types, preclose/afterday/future/unaware/rollback/memory clocks, record monetary/finish evidence. Test full envelope and schema1 cloud bundle with existing evaluation three scores, pending stops, negative wrong full-name prefix.
- [ ] Source tests use actual parser and memory store, mock only bounded transport and measured clock. Assert dryrun0, valid exact1GET afterclosed, count exceptionattempt1, max HTML1000000/10s, wrongURL/mime/size/status/errors no retry, rights/ownparent/currentday/preclose0GET, pending1GET0packet, actual postresponse capture/unchanged memory saved_at/no raw body.
- [ ] Run focused tests to establish RED; implement only the two modules; run focused GREEN and full unittest discover; self-review and commit own files. Write task report with schema/interface, RED/GREEN/full command counts, concerns, commit range. Do not touch live facts or workflow.

### Task 2: Forecast-scoped private result store, APIs and evaluation selection

**Files:** Create web/api/name_bound_result_store.py; web/api/publish-name-bound-result.py; web/api/name-bound-result.py; tests/test_name_bound_result_store.py; tests/test_name_bound_result_api.py. Modify web/api/name-bound-evaluation.py and tests/test_name_bound_evaluation_api.py only for validated separate-label-first selection.

**Interfaces:** Consumes Task1 exact packet/envelope/context/conversion. Produces publish_name_bound_result and read_name_bound_result with signatures/metadata/newnamespace rules from spec. GET returns full envelope; publisher resolves exact frozen forecast itself. Legacy report schema1 and JS unchanged.

- [ ] RED tests with fake Blob/auth/request seams and real contracts: exclusive canonical packet/receipt/marker/full readback, exact own pinned forecast, no writes to old prefixes, identical complete retry, conflicting/orphan/finalization/path/link/manifest rejection, monotonic latest sameforecast, current-day/postclose checks across actual I/O including finalread/midnight. Storage retry never overwrites existing nonce.
- [ ] Test publisher identical existing Preview/OIDC/commit gates, fixed no-secret errors, strict duplicate JSON/type/length/content-type/body parsing. GET exact query3fields maximum, missing404code, ownforecastmissing, invalid404vs422/store503, no source acquisition/writes, clientclose/no-store/noindex/nosniff.
- [ ] Test evaluation legacy absence parity, separate new label successful full3score replay, invalid separate label fails no fallback, other forecast namespace isolation and postread midnight. Do not modify pure evaluation/JS/old store.
- [ ] Implement minimal store/API changes, focused GREEN and full suite; self-review; commit owned files and report. No source/network/trusted edits.

### Task 3: Bounded caller, recoverable normalized evidence and manual mode

**Files:** Create scripts/publish_name_bound_result.py; tests/test_name_bound_result_caller.py. Modify scripts/verify_name_bound_evaluation.py only optional inventory_fn/verify_fn dependency hooks for reviewed finalize_manifest, preserve its defaults. Modify .github/workflows/boat-blob-e2e.yml only manual mode/input descriptions/new caller/upload/restore/verify steps. Keep current app pins until root live gate.

**Interfaces:** Consumes Task1/2 strict functions and GET/POST schemas. Produces run(race_id,forecast_request_id,output_dir,*,execute=False) and verify_backups(folder,manifest), sixfile inventory/manifest/CLI spec. Use existing REASONS/BudgetExhausted/finalize_manifest ownership recovery; callback defaults retain oldcaller tests. Workflow uses existing name_bound_race_id and name_bound_forecast_request_id (blank defaults), newcollection name-bound-result.

- [ ] RED: dryrun0FS/auth/network; full pipeline exact5applicationGET/1POST/1official; own forecast+name+label links and actual times, exclusive request beforePOST,6canonical files/fullhash/3score replay. Existing valid label stops3GET0source0POST; only exact404 NAME_BOUND_RESULT_NOT_SAVED permits collection, auth404/wrongbody/401/redirect/transport do not. Sourcepending/failure, no retries, currentday/preclose/unknowntarget/wrongnonce stop.
- [ ] Test all bounds and exceptions including auth/source/POST/readback/finalinventory/fullreplay/finalmanifestclose/timebudget; persist stopped actual inventory without truncating/replacing foreign manifest or following symlink. Deadline includes final I/O. Fullbackup restore rejects changes to every payload/type/counter/hash/schema/identity/clock; unchanged report.as_of uses existing remote60s allowance only.
- [ ] Implement, compile workflow Python blocks and validate exact manual predicates/security/blankinputs/default/probe-only push/source-smoke manual state. No workflow dispatch or trusted branch update. Focused GREEN including oldcaller21tests, full Python/JS suite once, self-review and commit only own files. Report any actual source/live gate remains root's responsibility.

## Root integration and live gate

After per-task clean review, one broad most-capable reviewer. Latest exact SHA Windows/Linux CI and READY before changing trusted code/pins. Preserve subject/env/concurrency/permissions/default/probe and both source-smoke manual-only. With all active-state/lease/JST/postclose/absent-source/own7proof checks, run new exact7R mode once. Full normalized artifact/API restore and independent three-score/label/clock audit. Actual protected UI result3rows and old4 full preservation; no unsupported video/physical-phase/adoption claims. Update PR64/evidence/state/heartbeat with actual IDs and constraints. Archive and remove only this plan's owned workspace once reviewed complete; final conveys every ruling and cost.
