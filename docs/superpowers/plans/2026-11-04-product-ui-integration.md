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
