# Name-bound exhibition implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development task-by-task. Owner authorizes autonomous routine design, implementation and Preview through completion; no repeated generic approval pause. One implementer at a time, fresh task review, no worker subagents.

**Goal:** Use an existing registration/name proof to save and show separate display/original numeric forecasts without changing any frozen B baseline or v1.

**Architecture:** Pure identity/input/model contracts, one three-source worker, immutable finalized store/API, bounded trusted caller and explicit comparison UI. Input-cloud readback precedes server model generation; existing finalized name evidence is reused.

**Tech Stack:** Existing Python3.12/SQLite/standard library/pinned Blob+JWT, plain JS/HTML/CSS and unittest/Node/browser tests. No new dependency or provider key.

**Spec:** `docs/superpowers/specs/2026-10-15-name-bound-exhibition.md`

## Global Constraints

- Owner branch `codex/race-ai-completion`, base8e04699a815389738d193762500ec082140b3834; preserve user/other-chat changes, main and Production.
- Preserve118 baselines and old post/display/original/video proofs. Do not rewrite B names, baseline bytes, old v1 validators or existing API/default variant behavior.
- Original frozen baseline validates against ORIGINAL B race; full-name context validates sources only. Original and projected identity SHA are separate, with exact immutable baseline/proof links.
- Reuse completed Marugame3R name proof38685125166-1 and baseline38676688119-1; no repeat racelist GET. Any different live target needs its own exact proof and current-day/cutoff check.
- At most3 source attempts, exact beforeinfo1MB/10s then2 original/standard TSV1MB/15s; no odds, redirects or retries. Missing display stops before TSVs. Existing owner scopes only; no permission re-request.
- All source capture/generation/runner/input-cloud/model/cloud/confirmation clocks same JST and strictly before closing. Parent reads complete before source/model use. Memory-save clocks are explicitly nondurable; real exclusive file readback and cloud readback clocks are separate.
- Every successful pinned/latest read requires exact immutable versions, original pinned parents and server finalization marker; orphan receipt stays ineligible. No latest write starts after close; marker/pointer durability is not timing evidence.
- Current exact OIDC verifier/ref/workflow/name/env/audience/subject/concurrency and All Deployments protection unchanged; no credentials/trust widening/Production/auto voting/payments.
- UNVALIDATED/skip/[]; ST/weather/video unused, physical pre-exhibition phase and model accuracy unverified. No raw HTML/TSV/media/frame/key/token/ephemeral URL retained.
- Source/model packet <=256000 canonical UTF-8 bytes, each backup and complete served envelope <=256000. New namespaces only; no old-source automatic PR trigger or legacy dated-source job execution.

## Review Focus

- Expanded names silently substituted into baseline validation would rewrite history; Task1/2 test separate original/projected digests and immutable baseline bytes.
- Finalized parent marker could have persisted later than its attested confirmation; record actual parent read completion before source/model generation, Tasks1–3 reject future/reversed parent times.
- Same nonce with changed inputs/runner/parent, or delayed input/forecast/receipt readback crossing close/midnight, must never finalize or become trusted later; Task2 covers orphan and pinned replay paths.
- Existing latest may pin a different baseline/proof; Task2 resolves previous own parents and Task4 renders the envelope's frozen comparison, never mutable baseline latest.
- Source/file/API latency, partial artifact corruption and delayed UI race responses must fail visibly without retry or cross-race display; Tasks3–4 own targeted tests.

## Task 1: Shared finalized-name replay, strict numeric input packet and source worker

**Files:** Modify `web/name_binding_contract.py`, `web/api/name_binding_store.py`; create `web/name_bound_inputs.py`, `race_ai/name_bound_exhibition_source.py`, `tests/test_name_bound_inputs.py`, `tests/test_name_bound_source.py`.

Extract current pure finalization logic into `name_binding_contract.validate_finalized_name_binding(envelope,race,baseline,*,now)`. Existing store's `validate_finalized_binding` delegates and retains exact error/envelope behavior. Use standard-library/existing pure evaluation/race imports; no cloud access. Preserve current contract/store tests.

Interfaces: `build_name_bound_inputs(beforeinfo_record,original_observation,race,baseline,binding,*,parents_read_at,generated_at,now)->dict`; `validate_name_bound_inputs(packet,race,baseline,binding,*,now)->dict`; `collect_name_bound_inputs(race,baseline,binding,*,parents_read_at,facts_review,media_review,execute=False,transport_update=None,transport_original=None,clock=utc_now)->dict`.

Input exact fields: schema_version1,kind=`NAME_BOUND_EXHIBITION_INPUTS`,race_id,date_jst,closed_at,program_identity_sha256,validation_program_identity_sha256,baseline_link,name_binding_link,parents_read_at,generated_at,beforeinfo_storage_scope=`SQLITE_MEMORY_NOT_DURABLE`,beforeinfo_record,original_observation,snapshot_id(selfSHA unsigned). Baseline link exact request_id,snapshot_id,receipt_sha256,b_program_sha256,cloud_saved_at. Name link exact request_id,snapshot_id,envelope_sha256,receipt_confirmed_at. All64lowerhex. Parent resolved/read time >= parent confirmation and baseline cloud time; <= minimum new source capture; max source capture and beforeinfo memory-save <=generated<=now, same day/preclose.

Validate original baseline and finalized binding first. Derive full-name context via existing projection. Strict `validate_record` for beforeinfo in that context, current-JST/preclose/AVAILABLE/all6display. Strict original observation validator in that context, AVAILABLE/all24, display equality per lane. Preserve raw B/parents. No artificial cloud receipts or expanded baseline.

Worker dry-run returns `{status:'DRY_RUN',official_source_requests:0}` with no GET; success `{status:'COLLECTED',snapshot,official_source_requests:3}`; stopped `{status:CODE,official_source_requests:N}` with fixed CODE among RIGHTS_BLOCKED,INPUT_INVALID,DISPLAY_PENDING,ORIGINAL_INCOMPLETE,SOURCE_UNAVAILABLE,SOURCE_INVALID,CUTOFF_PASSED,DAY_INVALID. Source attempts count at actual transport call. Check both owner reviews and parent/context/strict>120s margin before GET. Use exact fetch_update and fetch_original implementations/bounds. Parse beforeinfo with real post-response clock (never collect_race_update's supplied-start-clock mode), add owner rights reference, existing SQLite MEMORY store/write/readback gives actual memory-save clock. Tests may patch that module's utc_now, no production clock rewriting. Stop before TSVs if display incomplete. Each source step fresh clock/day/margin; parse original2TSVs then build packet. No raw source escapes worker.

- [ ] RED tests real existing beforeinfo/original fixtures with independent alias proof; swappedreg/name/date/cutoff/body, rawB immutability, original/source/display conflicts, SHA/pins, memory vs actual clocks, missing/reverse/afterclose/nextday, one/threeGET counts and safe failures.
- [ ] Implement minimal exact contracts/source; focused and existing name-binding tests then full suite once stable. Report/commit assigned files only, no network/push/workflow/subagents.

## Task 2: Two pure forecasts and immutable finalized Preview API/store

**Files:** Create `web/name_bound_prediction.py`, `web/api/name_bound_exhibition_store.py`, `web/api/name-bound-exhibition.py`, `web/api/publish-name-bound-exhibition.py`, `tests/test_name_bound_prediction.py`, `tests/test_name_bound_store.py`, `tests/test_name_bound_api.py`.

Interfaces: `build_name_bound_prediction(inputs,race,baseline,binding,*,runner_saved_at,input_cloud_saved_at,parents_resolved_at,now)->dict`; `validate_name_bound_prediction(snapshot,inputs,race,baseline,binding,*,now)->dict`; `validate_name_bound_envelope(envelope,race,*,now)->dict`; store `publish_name_bound_exhibition(request,race,*,client,now,clock=None)->dict`, `read_name_bound_exhibition(race,*,client,now,request_id=None)->dict|None`.

Prediction exact fields: schema_version1,kind=`NAME_BOUND_EXHIBITION_PREDICTION`,variant=`name-bound-v2`,phase=`post_exhibition_numeric_inputs`,race_id,date_jst,closed_at,as_of,generated_at,program_identity_sha256,validation_program_identity_sha256,baseline_link,name_binding_link,input_link,parents_resolved_at,boats,models,deltas,feature_status,research_only=true,validation_status=UNVALIDATED,purchase_decision=skip,purchase_recommendations=[],physical_exhibition_timing_verified=false,snapshot_id. Baseline link equals input link plus model_id selected existing rating elseuniform. Name link unchanged. Input link exact snapshot_id,sha256,runner_saved_at,input_cloud_saved_at. Generated serverclock >= input_cloud_saved_at >= runner >= inputs.generated; actual parents_resolved_at before input cloud and generation, >= parent confirmation; allsameJST/preclose.

Each boat exact lane,racer_registration_id,program_name,verified_full_name,display_time_s,original_times,base_strength,display_delta_seconds,contributions,total_original_log_delta,display_adjusted_strength,original_adjusted_strength. Contributions per4metric exact delta_seconds,coefficient_per_second,log_strength_contribution. Models2 ordered display thenoriginal, each exact model_id(`name-bound-display`/`name-bound-original`),model_version='2',parameters,triples,marginals,strengths as existing PL helper. Parameters explicit display1.0; original display1.0/lap.05/turn.20/straight.20; both clamp[-20,20]/rating_floor.01. Deltas2 ordered {model_id,triples,marginals}, same old _delta fields vs frozen base. Feature statuses include display/original used, ST/weather/video unused with reasons. Deterministic exact replay; no calling old `_assemble` with expanded baseline. Independent720-outcome tests required.

Exact served envelope `{receipt,finalization,inputs,baseline,name_binding}`. Receipt exact schema_version1,request_id,baseline_request_id,name_binding_request_id,snapshot,cloud_saved_at,cloud_eligible_pre_race=true. Marker exact schema_version1,race_id,request_id,snapshot_id,input_snapshot_id,baseline_request_id,name_binding_request_id,receipt_sha256,receipt_confirmed_at. Pure envelope validates linkedparents/input/model and allmarker hashes/times.

POST exact request {publication_review:existing facts REVIEW,media_review:existing media REVIEW,race_id,request_id,baseline_request_id,name_binding_request_id,inputs,runner_saved_at}. No client model/cloud clocks. Read existing immutable baseline+nameproof exact nonces, measure actual parent resolution AFTER reads; preserve runner/inputs. Namespaces `race-ai/name-bound-inputs/{race}/{inputid}.json`, `race-ai/name-bound-predictions/{race}/{snapshotid}.json`, `race-ai/name-bound-receipts/{race}/{nonce}.json`, `race-ai/name-bound-finalizations/{race}/{nonce}.json`, latest `race-ai/name-bound-exhibition/{race}.json`. Latest exact schema_version1,race_id,request_id,snapshot_id,input_snapshot_id,baseline_request_id,name_binding_request_id,program_identity_sha256,published_at. Store inputs/readback→actualinputcloudclock→serverbuild→forecastversion/readback→actualcloudclock→receipt/readback→actualconfirmation→marker→preclosecheck/latest. Never finalize orphan nonce on retry. Exact finalized retry same wholeenvelope, no writes even afterclose/sameday. Previouslatest resolvesown parents before comparing source-capture/generation/cloud/nonce position. API GET strict current race +optionalnonce, full canonical envelope; POST existingPreview/OIDC/SHA gate, no externalsourceGET. Metadata exact statusverified,race_id,request_id,snapshot_id,input_snapshot_id,baseline_request_id,name_binding_request_id,input_cloud_saved_at,cloud_saved_at,receipt_confirmed_at,sha256(fullenvelope),research_only,validation_status,purchase_decision,purchase_recommendations; routeaddscommit_sha.

- [ ] RED independent model vectors/720 permutations, identity/clock/tamper/fieldset/size cases; memory store write/readback latency/orphan/versionloss/idempotence/A-B-parentturnover, APIauth/query/commit/currentday and safeerrors.
- [ ] Implement pure model/store/APIs; focused/fullstable tests, report/commit assignedonly. No source/network/push/deps/v1 changes.

## Task 3: Bounded caller and exact trusted workflow mode

**Files:** Create `scripts/publish_name_bound_exhibition.py`, `tests/test_name_bound_caller.py`; modify only `.github/workflows/boat-blob-e2e.yml`.

CLI `--facts-review --media-review --output-dir --race-id --name-binding-request-id --execute`. `run(facts_review,media_review,output_dir,*,race_id,name_binding_request_id,execute=False)->dict|None`. Environment RACE_AI_NAME_BOUND_PUBLISH_URL/COMMIT_SHA, existingOIDC/positiveGHA nonce. Explicit currentdaytarget and nameproofnonce, no datedfallback. Dryrun noIO.

240smonotonic beforeOIDC,30sreserveperAPI/OIDC,10s+15s+15s eachsource,60sreservePOST+receiptGET, no retries;4APIreads max(today,proofpinned,baselinepinned,forecastpinned),1POST,3sourceattempts. Measure parents_read_at after proof+baseline complete. Write/readback baseline.json,name-binding.json,inputs.json; runner clock strictlyafterinputwrite/readback. request.json then freshJST/>120margin/budget guard, POST, pinnedfullGET, pureenvelope+exactmetadata/commit/request/runner/source replay. Write receipt.json(fullenvelope),manifest.json. Exactly6possible normalizedfiles,each<=256000, exclusivelynewdir/files andfullreadback; errors preservepartials/digests/status withno secret exceptions. Manifestexact schema_version1,statusCOMPLETED/STOPPED/TIME_LIMIT_REACHED,failure_reason fixed/null,race_id,request_id,name_binding_request_id,commit_sha,backups,reads_used,posts_attempted,official_source_requests,max_seconds240,validation_statusUNVALIDATED,purchase_decisionskip,purchase_recommendations[]. No recursivemanifestselfhash. Rootcross-runonceledger preventsunknown-outcome retry.

Workflow adds collection `name-bound-exhibition` and2emptydefaultinputs `name_bound_race_id`, `name_bound_binding_request_id`; quotedenvCLI only. Newmode alone runs caller, normalized6filesupload/download/fullcoverage+bytes+digest+status/counterverifier. Existingexactauth/concurrency/actions14days/sourcepredicates/manual-onlyoldsmoke/pushprobe-only unchanged. Currentappdc6fbcc/URLf1php leftuntilrootreviewedfreshCI/READY repin. Rootwillcheckbothbranchesbeforepush; no source-smokeautoGET.

- [ ] RED dryrun,missingparent0source,pinclock/source/budget/file/partialPOST/metadata/nonce/tampercases; compileembeddedworkflowPythonandmodeguards. Focused/fullstabletests, report/commit assignedonly,no network/source/push.

## Task 4: Explicit versioned comparison UI and final live gates

**Files:** Create `web/name-bound-exhibition.js`, `tests/ui_name_bound_exhibition.test.js`, `tests/ui_name_bound_exhibition_browser.cjs`; modify `web/index.html`, `web/app.js`, `web/styles.css` if it exists (otherwise actual existing stylesheet after rg), `.github/workflows/tests.yml` JScommand only to include new unitfile.

New UMD/CommonJS module exports `validateNameBoundComparison(value,race,now)` and `renderNameBoundComparison(value,race,now)` (returns escaped HTML); separate validation and view. Validate exact envelopenumeric/identity/clock/pin shape and replay bothPLmath+120deltas+allmarginals fromfrozenstrengths/input using tolerance1e-12; do not claim PythoncanonicalSHA recomputation using JSON.stringify floats. Use source-proof-linked full names only; preserve B names separately. Newcard/button explicitly reads `/api/name-bound-exhibition?race_id=...`; do notchangeoldv1readers/defaults. Display baseline, displayv2, originalv2 in comparison,6inputs/contributions/saveclocks,120triple/marginalchanges and clearunusedST/weather/video/physicalphase/UNVALIDATED messages. APIenvelopecontainsownpinnedbaseline; neverusecurrentlatestprediction silently. Missing/unavailable/tampered states clearcomparison. Racechange/generationguard preventsdelayedoldrace response. No generalapprefactor.

- [ ] RED JS numerical/hashformat/pin/source/delta/timing/HTMLescaping and selectedrace fixtures; onefocusedEdgebrowserflow includesB-abbreviatednameproof, two newmodels, oldv1retained, pending/error/staleresponse and1440/390viewportcontrols.
- [ ] Run newJS/browser and existingappropriateUI regressions; fullPython+JSonce stable. Finalindependentwholeincrementreview;rootpushDraftPR64,freshWindows/LinuxCI+READY,repinexistingtrustedworkflow. Rootoneeligiblelivejob onlyafteractualexhibitionpublication/currentJST/cutoff; no newracelist for15-03. FullAPI+6backuprestore+independent720replay+legacybytechecks andrealPC/mobilePreview; record precisecompleted/remainingstate/updateautomation. NoProduction/merge or repeatedcompleteddatedsources.
