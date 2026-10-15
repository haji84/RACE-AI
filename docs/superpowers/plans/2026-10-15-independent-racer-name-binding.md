# Independent racer-name binding implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Owner authorizes autonomous routine design, implementation, Preview and independent review through formal completion; no repeated generic approval pause.

**Goal:** Collect, validate, privately persist and fully restore an independent official registration/name proof bound to a frozen B-only baseline, without changing any legacy identity validator or forecast.

**Architecture:** A standalone web-safe contract validates a compact six-boat proof. A one-GET worker parses actual independent racelist bytes. A Preview-only publisher binds it to an existing verified baseline and saves separate immutable Blob versions/receipts. A bounded caller and explicit workflow mode provide actual source/API/backup evidence.

**Tech Stack:** Existing Python3.12 standard library, pinned Blob/JWT runtime and unittest; no new dependency or provider credential.

**Spec:** `docs/superpowers/specs/2026-10-15-independent-racer-name-binding.md`

## Global Constraints

- Work in the owner-specified clean `codex/race-ai-completion` checkout. Base0525d8670631ad31094ee6031fc154dea4870524; no other chat/user change overwritten.
- Preserve118 baselines, Toda1 displayv1, Naruto8 originalv1, Naruto7 video and Amagasaki5 video; all current future baselines already verified, so no cohort/day/source repeats.
- No v1 validator, prediction model or original B name rewrite. New identity contract/version/namespaces only; actual alias-aware prediction integration is subsequent, not claimed done.
- Source is only exact `https://www.boatrace.jp/owpc/pc/race/racelist?rno=N&jcd=VV&hd=YYYYMMDD`; oneGET, existing1MB/20s/no redirects. Existing owner confirmation only, no repeated permissions.
- All6 lanes/registrations/body/date/cutoff verified. Prefix alone never establishes identity; mismatching names require exact4-character B abbreviation plus the independent complete registration proof. Other name changes reject.
- `program_identity_sha256` comes from the unchanged B race. `baseline_snapshot_id` and `b_program_sha256` pin the verified original baseline, even if the current-day B archive hash later differs.
- Source capture<=generation<=runner exclusive write/readback<=actual cloud readback<=now; same JST day, all publishing clocks strictly before closing. No late receipt/latest; an orphan version after delayed readback does not establish a receipt or eligibility.
- Existing OIDC verifier/settings/name/ref/environment/audience/subject/concurrency remain exact; no secrets or privilege expansion. Existing upload/download artifact actions/policies unchanged.
- No raw HTML/media/frame/key/token/ephemeral URL retention or public forecast data. Normalized six-name proofs are protected facts; public evidence contains engineering counts/hashes only.
- UNVALIDATED, skip, empty recommendations; no Production, merge, auto betting or payment.

## Review Focus

- A lookalike registration/profile URL, swapped lane or detached schedule must not establish a name binding; Task1 tests body and registration tampering.
- Same-prefix/different registration, arbitrary suffix without independent source proof, non-abbreviation rename and missing six-lane evidence reject; Task1 tests all.
- A valid proof for another baseline/B archive/program or future capture cannot be reused silently; Tasks1–2 test pinned identity, receipt chronology and exact replay.
- Same nonce with changed proof, delayed body readback crossing close/midnight, older correction and missing immutable body cannot produce a trusted latest receipt; Task2 tests bounded store failures.
- Source/runtime/API/file latency, local tampering, post-response mismatch, source rights failures and unknown publication outcomes retain partial normalized evidence without backdating or blind retry; Task3 tests these paths.

## Task 1: Strict standalone proof contract and one-GET collector

**Files:** Create `web/name_binding_contract.py`, `race_ai/name_binding_source.py`, `tests/test_name_binding_contract.py`, `tests/test_name_binding_source.py`.

**Interfaces:**
- `build_name_binding(detail,race,*,baseline_snapshot_id,b_program_sha256,generated_at,now)->dict`
- `validate_name_binding(snapshot,race,*,baseline_snapshot_id,b_program_sha256,now)->dict`
- `validate_name_binding_receipt(receipt,race,*,baseline_snapshot_id,b_program_sha256,now)->dict`
- `project_name_bound_program(snapshot,race,*,baseline_snapshot_id,b_program_sha256,now)->dict`: a deep copied explicit validation context only; original race/receipt stays unchanged.
- `collect_name_binding(race,*,baseline_snapshot_id,b_program_sha256,review,execute=False,transport=None,clock=utc_now)->dict`: dry-run before any network; execute parses one exact response using `parse_official_racelist`, then builds snapshot. Errors are fixed safe codes; no raw response output.

**Snapshot exact fields:** schema_version1, kind=`OFFICIAL_RACELIST_NAME_BINDING`, race_id, closed_at (canonical stamp), baseline_snapshot_id, b_program_sha256, program_identity_sha256, generated_at, capture_eligible_pre_race, source, bindings, snapshot_id. Source exact fields: source_url, source_sha256, captured_at, available_at(=capture), upstream_published_at(null), body_identity_verified(true), parser=`official-racelist/v1`, observed_racers (6 rows exactly lane/racer_registration_id/name). Bindings exactly lane/racer_registration_id/program_name/verified_full_name/name_relation. Self-hash is SHA256 canonical unsigned snapshot. Entire snapshot<=64000 bytes, six distinct valid registrations/lanes, visible bounded names and exact field sets. Baseline IDs/archive SHA/program SHA are64lower hex.

**Receipt exact fields:** schema_version1,request_id,baseline_request_id,snapshot,runner_saved_at,cloud_saved_at,cloud_eligible_pre_race,baseline_snapshot_id,b_program_sha256,program_identity_sha256. Nonces use existing positive run-attempt format. Receipt is current-JST-date, all source/generation/runner/cloud clocks strictly before closing, never supplied cloud clocks when publishing.

- [ ] Write meaningful failing tests using the actual existing racelist fixture/parser:4544 松田大志→official observed full name, normal whitespace, body date/lane/link/registration swaps, false suffix and other rename, all clocks/sha/fields, and immutable B byte equality.
- [ ] Verify RED, implement minimal pure contract/collector; inspect existing source rights and FetchResponse before using them. Collector uses owner config's exact racelist path, same-JST current program, pre-GET120s margin and rechecks real post-GET clock. Parser source-clock supplied fixture is not an actual network/save claim.
- [ ] Run focused tests then full suite at stable code; report every failure. Commit only assigned files with per-command Codex identity, do not push or start source/network calls.

## Task 2: Immutable Preview proof API/store

**Files:** Create `web/api/name_binding_store.py`, `web/api/name-binding.py`, `web/api/publish-name-binding.py`, `tests/test_name_binding_store.py`, `tests/test_name_binding_api.py`.

**Interfaces:** `publish_name_binding(request,race,baseline,*,client,now,clock=None)->dict`; `read_name_binding(race,baseline,*,client,now,request_id=None)->dict|None`. Baseline is an existing fully verified prediction receipt loaded with `read_prediction` and `_checked_prediction`; never recompute/replace its frozen statistics. Exact request fields: publication_review=`user-confirmation-2026-10-15-official-facts`,race_id,request_id,baseline_request_id,snapshot,runner_saved_at.

**Namespaces:** `race-ai/name-binding-versions/{race_id}/{snapshot_id}.json`, `race-ai/name-binding-receipts/{race_id}/{request_id}.json`, `race-ai/name-binding/{race_id}.json`. Latest exact fields: schema_version1,race_id,request_id,snapshot_id,baseline_snapshot_id,b_program_sha256,program_identity_sha256,published_at. Position by(source capture,generation,runner,cloud,request_id). Immutable body readback before cloud timestamp; immutable receipt readback before latest. No overwrite on version/nonce, only verified latest may overwrite. Same nonce exact retry returns same receipt, changed proof/runner/base rejects. Publish must be before close; GET may inspect saved pre-close proof after close on same day. Maximum JSON64000 bytes.

**API:** POST `/api/publish-name-binding`, Preview only with unchanged existing GitHub OIDC and exact deployed app SHA header. Verify current approved day, race and pinned existing baseline nonce before store; no external official source fetch in server. GET `/api/name-binding?race_id=...&request_id=...` strict bounded query, protected by existing deployment protection; fetch current verified baseline/validate frozen proof. Fixed errors, no secret logs. Read responses carry full receipt, publish response metadata includes snapshot_id, request_id,baseline links,runner/cloud times,sha256 andcommit_sha.

- [ ] Write RED tests with in-memory strict Blob/readback helpers; test malicious fields/baseline/B/clock/source metadata, idempotence, correction/older latest, immutable loss, delayed close/midnight, and no v1/old baseline writes.
- [ ] Implement using existing Blob primitives, per-command imports work standalone underweb Vercel root. No modifications to OIDC/today/prediction/race/original modules.
- [ ] Run focused and full tests, write report/commit assigned files only; no push/network.

## Task 3: Bounded caller and explicit trusted workflow mode

**Files:** Create `scripts/publish_name_binding.py`, `tests/test_name_binding_caller.py`; modify only `.github/workflows/boat-blob-e2e.yml` locally.

**Interfaces:** `run(review_path,output_dir,*,race_id,execute=False)->dict|None`; CLI `--review --output-dir --race-id --execute`. Existing `workflow_session`, bounded `get_json`, approved day selection and `_checked_prediction` reused. Environment RACE_AI_NAME_BINDING_PUBLISH_URL and RACE_AI_NAME_BINDING_COMMIT_SHA, nonce positive GITHUB_RUN_ID/ATTEMPT. Exact explicit current-day future ID required; no fallback dated target.

One OIDC session; read today+existing baseline; validate and pin baseline before one collector GET; write/exclusively readback `baseline.json`,`name-proof.json`, stamp actual runner time; write/readback `request.json`; pre-POST JST/120s recheck; POST and pinned receipt GET; full contract+response/baseline/nonce/commit replay, exclusive `receipt.json`; finally `manifest.json` even partial errors. All5 normalized files<=64000 each, no source original retained. Monotonic180s budget starts before OIDC/feed; reserve30s each API read,60s for POST+readback; no operation begins without budget, source20s reserved. No retry. Manifest pins complete file bytes/SHA and explicit COMPLETED/STOPPED/TIME_LIMIT_REACHED with actual counters, all model states unchanged. Baseline unavailable stops before source GET.

Workflow adds collection choice `name-binding` and explicit input `name_binding_race_id` default empty. New step only for explicit mode, caller and normalized-only upload/download/full byte+digest verifier(max5 files) mirror existing patterns. Push performs existing probe only; remove automatic cohort push condition to prevent re-reading a completed all-upcoming collection when wiring the proof mode. Explicit cohort/day/race/result/exhibition/original predicates remain. Do not change currently pinned app/Preview yet; root pins fresh reviewed CI/READY app after commits, then leases exact remote workflow update. No cron, new permission, environment, OIDC verifier or concurrency change.

- [ ] RED tests: dry-run0GET, absentbaseline0officialGET, rights/response/source failure, actual source/generation/runner/cloud order, midnight/cutoff/file/tamper/budget guards, mismatched receipts/commit and all backup bytes.
- [ ] Implement caller/workflow; compile embedded Python and verify existing modes unaffected. Use same action SHAs/retention14days. Commit assigned files only; no push/dispatch/source GET.
- [ ] Root completes independent staged/final review, full Python/JS/Windows+Linux CI and READY Preview; pins exact reviewed app/URL via leased existing workflow. Push probe must not acquire sources; explicit name-binding target chosen from new eligible day program. Root dispatch once, restore all normalized backups and compare full protected API, independent replay and legacy receipt hashes. Record usable identity foundation and remaining alias-aware prediction integration precisely; update PR64/state/heartbeat, preserve Draft/Production.
