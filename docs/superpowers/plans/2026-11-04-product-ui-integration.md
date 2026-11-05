# Existing PR71 product UI integration plan

> **For agentic workers:** Use the existing isolated checkout and coordinate file ownership; no new development PR, scheduled task, workflow, or worktree.

**Goal:** Implement the approved eight-reference responsive UI and a read-only path for saved predictions, preserving evidence and scope.

**Architecture:** Reuse PR62's vanilla seven-page shell and pure allocation helpers, with PR71's audit schema behind a strict local-import adapter. UI state never invokes source acquisition or model inference. Existing audit viewer and model engines remain available.

**Tech stack:** HTML/CSS/JavaScript, Node built-in tests, existing Python suites, Playwright with Chromium.

**Spec:** `docs/CODEX_RACE_AI_UI_PRODUCT_COMPLETION_20261104.md` (owner-approved); attached eight JPGs inspected, not a data source.

## Global constraints

- Only the existing `feat/four-sport-forecast-audit-view-20261022` branch / Draft PR71 is a write target; preserve concurrent commits with ordinary fast-forward push.
- No Cloudflare, Vercel, paid services, new workflow, schedule, model family, main merge, public deployment, actual bet, or production model switch.
- No raw private predictions or purchase records in public assets, logs, or commits; browser imports are local and not automatically persisted.
- Synthetic, research, imported evidence, and independently admitted official records remain distinct. Never display uncalibrated probabilities or fictional performance.

## Audit and reuse matrix

| Existing asset | Reuse / change | Boundary |
| --- | --- | --- |
| PR62 `web/index.html`, `style.css`, `app.js`, `ui-model.js` | Reuse responsive shell, navigation, ticket/budget utilities; replace boat-only feed and integration | No dependent PR merge, `/api/today`, periodic requests, or Coming soon |
| PR71 audit model and viewer | Reuse validation, immutable predictions, model/result evidence; keep viewer accessible | Strict product adapter adds scope/stage separation |
| PR64/72 | Existing CI-pinned parsers/normalizers used for regression checks | No wholesale merge |
| PR71 cycle recovery / observed learning | Validate existing offline continuation tests and inspect saved execution evidence | No restart or increase of existing source budget |
| Eight supplied reference JPGs | Layout, hierarchy, color, responsive navigation | No portrait, sample identity, odds, or performance copying |

## Execution

- [x] Adapter: failing Node tests for local audit import, scopes, metadata, stages/models, revision contradictions and original preservation; implement `web/product-data.js` with `RaceProductData.parse/summary/selectPrediction/modelGroups`.
- [x] UI: failing pure model tests; transplant the PR62 shell and implement seven pages in `web/index.html`, `style.css`, `app.js`, `ui-model.js`. Support sport/day/search/filter, detail tabs/evidence/model-stage switching, candidate amount editing/limits/confirmation, separate manual purchase, settings and results/research.
- [x] Browser: `tests/ui_browser.test.js` exercises 320/390/1440/1920, all seven pages, four sports, long text/empty data, local import, candidates, midnight/state, keyboard, and source-network absence; retain synthetic-only screenshots and trace.
- [x] Regressions: run existing Node and Python suites with exact pinned PR64/72 reference directories; add product checks within the existing viewer CI job only.
- [x] Review: independent code review, fix reproduced failures, inspect screenshots against all eight originals, record residual gates.
- [x] Save: append evidence/results/limitations to `docs/RACE_AI_LATEST_STATUS.md`; recheck upstream HEAD, commit and ordinary push to existing PR71 only; check exact-SHA CI where access allows.

## Review focus

- Imported booleans alone cannot establish independent freeze/result verification.
- P0/P1/model versions and corrected results cannot silently replace original predictions.
- Missing forecasts remain in applicable full-cohort denominators; synthetic/research rates cannot become official performance.
- User draft candidates cannot count as actual expenditure; private records cannot leak through browser persistence or screenshot evidence.
- Day rollover, long labels, 320px width, and navigation must retain truthful, usable state.

## Progress and rulings

- Owner supplied the approved product design and explicitly requested implementation, so no additional design-approval pause or new product-design task is introduced.
- Initial PR71 HEAD: `c15e683d520ba248526800c8a35c161735a2d565`. Main HEAD: `0e45c029e18d5f3f1e7a04aecedab3c4af261748`. Clean checkout switched to the existing PR71 branch.
- GitHub API requests return Forbidden under the current network policy. Public GitHub web pages and native Git fetch work; API-only writes/Actions artifact access are not yet verified.
- Existing private real forecast payloads are not mounted. Local import plus explicit synthetic fixtures is the authorized first acceptance route; it is not live real-race validation.

- First ordinary push was rejected when concurrent writer e587f5a arrived. Fetched and merged that documentation-only update without reset/force; retained its final-cycle audit and explicitly distinguished its provenance. Application/test trees are unchanged by this merge.

- d419d8b pushed after preserving concurrent e587f5a. Existing viewer41814145631 and AUTORACE41814145656 completed/success for this head; evidence documents updated separately. Issue API writes remain blocked.

## Owner follow-up: every race / every existing applicable model

- Keep all16 existing families; enumerate actual supplied race identities × applicable models/stages/versions, not count-only completeness.
- Add native-input offline dispatcher reusing original algorithm calls, retaining every returned model and preserving saved originals before filling missing siblings. No live fetch, workflow change, storage-provider change, or model promotion.
- Reuse unchanged PR72 OwnerPrivateFileReader and original tests in PR71 to support pinned read-only bytes; investigate real source locations, never mistake synthetic encrypted checkpoint for real private history.
- Local source search found no known original filename in mounted Library/shared/Downloads roots. GitHub private-reader documentation identifies the previous owner Library bundle and original SHA; encrypted Git history latestmode=synthetic. Remote API permission remains unapplied.
- Physical iPhone Safari is not attached. Chromium operation proof remains separate from physical-device acceptance.
- Tests and independent review precede ordinary push to existingPR71, preserving concurrent writer changes. Report realexecution separately from software fixtures.

### Follow-up local implementation complete / live gates open

All16nativealgorithmswired+exercised, strict fullslotmatrix, unchangedPR72readerreused, UIall16visible. Python618/Node165/4widths25browsergroups green, independentmaterialfindingsfixed. Liveprivateinput0, liveall-race16notdone, physicalSafariunattached, sourcecapnotchanged, no modelpromotion. Exact-headCI willbecheckedafterordinarypush.

## Authorized continuation: real originals, four-sport operation, Safari, prospective comparison

Owner explicitly requested continuing these four requirements to completion. Existing product spec/branch/workflow/model families remain authoritative; no new task or approval pause for implementation.

- [x] Investigate native source→dispatch→private persistence: the existing AUTORACE journal key omits sport/version and cannot simply accept P0/P1. Add an additive `PrivateDispatchJournal` operation API that keeps legacy tables intact, atomically loads immutable originals and persists every slot under sport/race/stage/model/version. Reuse lossless codec primitives so integer-key horse metadata retains native hashes.
- [x] Require existing source authorization for analysis/private storage/private derived use. Bind real imported originals to native input commitments without inference. Reject unsupported legacy commitments explicitly. Fix scope relabel bypass found by independent review.
- [x] Project exact native outputs into private display, including all16 families, native AUTORACE phases, missing race metadata and seller's saved5-ticket plan. Do not call that plan Top8 or invent missing native SHA. Keep output-content SHA, model/training SHA and native prediction SHA separate.
- [x] Add pure BOAT saved-original comparison with pinned versions/training references, full declared schedule, exact result captures and missing-original denominators. No replay, fitting, fetching, official-proof promotion or auto-adoption. Repair malformed finish-order acceptance found by review.
- [x] Verify actual native outputs and private SQLite reopen→view→browser on synthetic inputs, all16 families, native phases, missing phases, plan labels and null metadata. Python724/Node175 after preserving the concurrent JRA gate, browser31groups/48PNGs; source-provider GET0. Independent material findings fixed/reviewed.
- [ ] Acquire actual originals in this environment and compare SHA/Top8/P1/result history in browser. Current runtime still denies api.github.com; known Library originals remain unmounted. Draft network/start instructions saved; user could not find settings, so guide using visible menu evidence. Do not bypass policy.
- [ ] Attach and accept on physical Safari. Chromium and synthetic coverage remain separate.
- [ ] Complete four-sport/all-race/all-applicable-model real inputs, independent pre-cutoff retention/results and forward improvement evidence. Local APIs/tests do not satisfy this live requirement.

Code, local validation and external blockers are recorded separately in `RACE_AI_LATEST_STATUS.md`; recheck concurrent remote writers before ordinary push.

## Authorized continuation: generate new forecasts from the app

The owner explicitly requested new generation after confirming that the earlier application only displayed saved originals. Continue in PR71 without another design/permission pause, publication, new model family, workflow or scheduled task.

Architecture: retain the existing web shell and native dispatch/journal. A loopback-only Python server injects an API capability into its served HTML. The browser sends only sport/stage on an explicit click. A trusted current-day provider captures exact official bytes privately, creates unchanged native inputs, and admits only the current personal-analysis/private-storage/private-derived scope. Static imports continue to work without an API probe.

- [x] Capture and strictly parse current official BOAT B input, keeping missing fields missing and exact source SHA/capture clock. Deduplicate source reads across restarts; persistent request bounds and 4xx/identity stops. P1 reuses existing strict official page parsers, at most3 new races per manual call; pending sources remain pending.
- [x] Wire current inputs through all registered slots to the unchanged native algorithms, immutable journal and existing product projection. Add a real save-clock check with210second buffer; late/reversed/unknown save times remain rejected even on retry, without regenerating originals.
- [x] Add loopback Host/Origin/nonce boundaries, a fixed static asset list, bounded POST and exact sport/stage fields. No browser-provided time, source URL, grants or private path. Private files are never static assets.
- [x] Add explicit P0/P1 generation controls, counts for generated/reused/missing model slots, returned-day/original validation, failure retention and honest unavailable sport states. Avoid calling synthetic API fixtures live proof.
- [x] Actual Nov5 app click generated144races/288P0 originals; retries0new/288reused. Full1440 plus390 representatives checked294variants/2352tickets; sourceGET1; all829Python/179Node/35syntheticbrowsergroups passed. Independent review matched all288native SHA/Top8 againstHTTP/retry/package JSON without inference.
- [x] Delivered a verified private launch package with pinned PR64/72 code, exactsourcebytes/seedDB/currentJSON. Isolated imports+seed/check+0GET/0inference/288reuse passed. Linux/POSIX or WindowsWSL2 is required; cloud127.0.0.1 is not the user's PC URL and staticHTML is not an inference server.
- [ ] Record remaining actual inputs for other sports/models, P1 source/cap coverage limits, independent retention/results, physical Safari and precision improvement. Do not claim whole-product completion from the first2 BOAT models.

## Authorized continuation: automatic forecasts without a button

The owner explicitly requested automatic generation after the manual app was delivered. Reuse the existing bounded-round policy inside the existing local server; no new cron, workflow, external service, model family or approval pause. Earlier manual-generation entries above remain the historical checkpoint.

- [x] Start the app-owned controller only when HTTP serving begins, after a successful loopback bind; `--check`/factory construction never collect or infer. Stop the worker with server shutdown and prevent duplicate writers at the private profile lock.
- [x] Keep180second rounds, maximum24rounds/65minutes,240source attempts per JST day and midnight stop. Persist the session origin, progress, next due time, source counter and stop reason; restart cannot reset limits or silently replay an interrupted round.
- [x] Complete P0 once and preserve original models/versions/SHA/Top8; poll only due P1 inputs under the existing race/request limits. Missing exhibition remains missing. Automatic collection does not create an external freeze or replace the GitHub first-receipt registry.
- [x] Publish checked journal originals to read-only `status`/`latest` endpoints. The browser autoloads saved forecasts without clicks and polls status every180seconds; changed revisions cause GET reads only. Reject manual generation while automatically managed, including bounded-stop states.
- [x] Preserve edited/confirmed candidate amounts, selected original SHA, filters and detail tabs across updates. Defer unblurred edits, retain current P0 while P1 is unavailable, keep manual imports under manual display ownership, validate server day/sport/stage and resume reads after browser restoration.
- [x] The initial fullPython871/Node179passed; full synthetic browser37groups/58PNG had no page errors. Startup/no-click/GET-only tests are software integration evidence, separate from actual forecasts and real-source metrics. Shutdown-race follow-up and its final validation counts are recorded in RACE_AI_LATEST_STATUS.md.
- [x] Actual local automatic check reused288 current-day P0 originals; P1new0 remained input-pending. Four rounds completed/sourcecounter3. Root's stop at2026-11-04T23:18:21UTC raced the fifth round's start after existingrun41929106428 was found in progress. The original process exited; preserved the fifth-round marker and verified restart latches INTERRUPTED_ROUND_REQUIRES_REVIEW with0GET/0inference. The server now serves saved originals with automatic generation STOPPED. Do not count round5 completed or label the local worker running; preserve both local originals and concurrent upstream work.
- [ ] Full-day/all-race P1, all four sports/all applicable models, independent result collection/retention, physical Safari and measured prospective improvement remain open. No always-on service, new results collector or whole-product completion is claimed by this automatic-generation change.

- [x] Final shutdown fix23controller tests, independent40test review, fullPython877/Node179 and37syntheticbrowsergroups passed. Existing GitHub run round11 independently saved P0288 plus P1five variants668seconds beforecutoff; canonical293 remain separate from earlier local288 originals. No provider/inference used for readback.

## Authorized continuation: remove automatic-path GET count limits (2026-11-05)

The owner explicitly requested no retrieval count limit. This supersedes the earlier240 cumulative/45 per-call count policy for the automatic forecast path. Represent unlimited withPythonNone/JSONnull, keep real counters (strictnonnegativeinteger, no reset), and remove count-only stops from the existing session guard, provider, localservice/controller andactiveP1pilot. This is a change inside the existing path; legacy one-shot diagnostic probes retain their separate scope. No huge sentinel or Infinity.

- [ ] Write failing regression cases for continuation beyond240 cumulative and45 per-call GETs, preserved legacy counters/metadata, automatic service/controller restart, unchanged original forecasts and old stopped-state latches.
- [ ] Remove count ceilings while preserving180s cadence,24round/65min/dayboundary,3fresh-race workload,210s cutoff, locks/identity/privacy and HTTP4xx/429 stop conditions. Keep expiry/timeouts/response-byte validation.
- [ ] Expose explicit unlimited count metadata/status, retain legacy stopped-reason interpretation and test browser rendering without generationPOST.
- [ ] Run focused and full Python/Node/browser checks; independent review current source and safe evidence. Keep live originals unchanged and do not reset/restart the active GitHub worker.
- [ ] Record implementation vs active-run rollout separately in RACE_AI_LATEST_STATUS.md. Current publicrun41964059991 is pinned to olderheadfea5b2a4; local edits cannot retroactively alter it. No push, environment publication, new workflow/task/PR/model or paid service.
