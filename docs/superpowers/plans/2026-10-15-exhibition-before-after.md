# 展示前後の予測と展示映像・オリジナル展示データ

**Goal:** Preserve both the existing exhibition-unreflected baseline and a separately saved exhibition-informed forecast, explain their probability changes, then integrate verified original exhibition times and permitted video-derived features across all races.

**Authority:** Owner requests on2026-10-15: both 展示前/展示後 predictions visible, all-race exhibition-video analysis and original exhibition times used in prediction. Separate video owner attestation:「ファイルパスはないが利用していいと調べたら出てきた。」No underlying legal research file supplied; record owner attestation only. Ordinary development/testing/protected Preview is autonomous. Production/betting/payments remain excluded.

**Base:** a8c309371f7824c3f55f620a8c6568e55453c1d4;534Python perOS(one optional skip),44JS,6Edge regressions;14actual B-only forecasts,1evaluated result. Historical reading design saved in artifacts/local/historical-read-design.md but implementation deferred for this user priority.

## Design and boundaries

- Existing baseline receipts, pointers, as-of and actual save times remain byte-for-byte unchanged. The baseline label is「展示前予想（展示情報未反映）」; this describes the input phase and does not assert unknown physical exhibition/publication times. Show actual source/forecast/save timestamps.
- New pure `web/exhibition_contract.py` freezes a valid existing baseline and full verified beforeinfo receipt. Six nonnull finite display times required; current beforeinfo AVAILABLE alone is insufficient (ST-only observations can be AVAILABLE). Use neither result/final-market facts nor assumed course/undated weather. All source capture/runner/cloud saves <=actual as_of<=generation<close; actual new durable save also before close. No backfill.
- Separate B archive SHA and roster/cutoff identity digest. Select the frozen rating-point baseline model if present, otherwise uniform. Names/registrations/lanes/cutoff must match the pinned source; roster correction cannot silently rebind the earlier prediction.
- First executable model is explicitly untrained: `official-beforeinfo-display-pl/v1`; six base strengths from the linked baseline; display delta=mean six display times minus each time; adjusted strength=exp(clamp(log(base_strength)+1.0*delta,-20,20)). Existing PL computes120triples and six rank marginals. Fixed coefficient1.0 persecond, clamp[-20,20], floor0.01 are versioned experimental parameters, not learned evidence. Equal display times preserve baseline probabilities. Output all probability deltas and the actual display contribution; no causal claim for unused factors.
- New immutable post prefixes and API do not replace baseline paths. Read/retry must load the exact pinned baseline request and beforeinfo snapshot, never latest changed data. Same scoped Preview OIDC and serialized writer, no new keys or trust.
- UNVALIDATED/research_only/skip/empty purchase_recommendations persist. UI may show research combination probabilities; it must not label those validated recommendations or assign funding.
- Official original lap/straight/turn times and video-derived measurements remain distinct with exact venue/race/boat identity, measurement definition, units, capture/analysis/actual cloud times, source hash and confidence/calibration. Missing/unused features are explicit and cannot silently alter v1 probabilities. They are required following increments, not completed by adding empty fields.
- Video owner confirmation permits bounded official exhibition acquisition and private analysis/temporary processing. Original media is not added to public builds or fact backups; persistent raw-video retention/public redistribution/independent legal audit are not asserted. Public official player/CDN source identities must be verified; no login/DRM/access-control bypass.

## Exact post bundle interface

`build_post_exhibition_bundle(baseline_receipt, race_bundle, race, now)` and `validate_post_exhibition_bundle(bundle, baseline_receipt, beforeinfo_receipt, race, now)`.

Exact bundle keys: `schema_version:1,phase:'post_exhibition',race_id,date_jst,closed_at,as_of,generated_at,program_identity_sha256,b_program_sha256,baseline_link,beforeinfo_link,boats,feature_status,model,deltas,research_only:true,validation_status:'UNVALIDATED',purchase_decision:'skip',purchase_recommendations:[],snapshot_id`.

`baseline_link={request_id,snapshot_id,receipt_sha256,cloud_saved_at,model_id}`. `beforeinfo_link={snapshot_id,receipt_sha256,source_url,source_sha256,captured_at,runner_saved_at,cloud_saved_at}`. Six boats: `{lane,racer_registration_id,display_time_seconds,base_strength,display_delta_seconds,adjusted_strength}`. `model={model_id,model_version,parameters,triples,marginals,strengths}`. Parameters exact values above. `deltas={triples,marginals}` with identities and baseline/post/signed delta probabilities. `feature_status` separately identifies used display, observed/partial/missing unused ST, unknown-time unused weather, missing original timings and missing validated video features. Details reside in artifacts/local/exhibition-model-design.md; implementer must freeze these nested field names and send UI the precise emitted JSON example before UI consumes it.

Post receipt exact fields: `schema_version:1,request_id,snapshot,cloud_saved_at,cloud_eligible_pre_race:true,program_identity_sha256`. Post paths: `race-ai/post-exhibition/{race_id}.json`, `race-ai/post-exhibition-versions/{race_id}/{snapshot_id}.json`, `race-ai/post-exhibition-receipts/{race_id}/{request_id}.json`.

`POST /api/publish-exhibition-prediction`: existing pinned OIDC/Preview/commit guards; exact request `{publication_review:'user-confirmation-2026-10-15-official-facts',race_id,request_id}`; server reads baseline and observations, chooses clocks/model. Success verified receipt digest/snapshot/save metadata; incomplete evidence fails closed with a fixed reason and no post receipt/manifest. `GET /api/exhibition-prediction?race_id=... [&request_id=...]`: strict bounded current-day read, original receipt or404missing,422corrupt,503store, no-store/nosniff/noindex. Retry after close may only serve an already valid receipt, never construct a new forecast.

## Task1: Backend forecast and durable proof

Owner: backend implementer. Own `web/exhibition_contract.py`, `web/api/exhibition_store.py`, `web/api/exhibition-prediction.py`, `web/api/publish-exhibition-prediction.py`, corresponding new Python tests. May narrowly extract full cloud receipt validation into `web/race_contract.py` +wrapper in `web/evaluation_contract.py`; do not alter existing external contracts/current-day writers. No browser/script/config/docs edits or external mutations/commits.

- [ ] TDD pure display adjustment/equal-time invariance,120probability/delta sums, exact links and identity/digest distinctions, actual clocks, incomplete ST-only data, rehashed tampering and input immutability.
- [ ] TDD immutable post storage/retry/correction, pinned old beforeinfo and baseline replay after latest revisions, actual save after immutable readback, close/midnight/nonce/size failures. Existing baseline store keys untouched.
- [ ] TDD read-only and scoped-publish API strict queries, errors, missing state, resources, full read chain and no caller probabilities/times. Run focused/full Python tests and send exact nested JSON fixture/interface to UI.

## Task2: Side-by-side comparison and every-race visibility

Owner: UI implementer after exact JSON fixture is sent. Own `web/exhibition.js`, narrow `web/ui-core.js`, `web/app.js`, `web/index.html`, `web/style.css`, new JS tests and browser regression. Backend agent owns Python. Root owns CI and existing browser allowlist updates.

- [ ] TDD response replay/identity/cutoff/baseline-link and slow-old-race rejection. Missing post forecast cannot be shown as a calculated update; fail/reload/race/day changes clear it.
- [ ] Show exhibition-unreflected baseline and post forecast with saved times, 6boat probability changes,120combination deltas, used display measurements and fixed research coefficient. Clear missing/unused original/video/weather/ST states. Keep original baseline model switch and result evaluation available.
- [ ] Desktop parallel blocks; mobile accessible selector/stack. Do not hide uncertainty, assign AI grade, recommend money or fake video analysis. All race cards expose honest phase status/availability without156unbounded API calls.
- [ ] Run all JS/six existing+new Edge regressions, syntax and full Python integration checks. No actual Preview purchase records.

## Task3: Actual data/media and integration

Owner: root, source adapter implementer when concrete sources are verified, independent reviewer.

- [ ] Record separate media owner confirmation and verified official source mappings; inspect actual original-data/player supply. Build bounded automatic collectors with complete dated identity, source hashes, no originals in public artifacts and explicit missing/unsupported cases.
- [ ] Install/use a pinned private video processing runtime if needed, perform actual decoding/boat identification/measurements with uncertainty and ground-truth checks. Indexing frames alone is not boat/foot performance analysis. Only validated pre-cutoff derived feature receipts enter a subsequent versioned model; v1 display-only remains transparent.
- [ ] Add scoped workflow mode for baseline-preserving preview acquisition then post generation; exact reviewed app+Preview pins, existing concurrency/OIDC. No completed-result polling, no unapproved extra day collection.
- [ ] Independently review, test, push, verify exact-head Windows/Linux CI, real source→cloud→postprediction→API→browser comparison and frozen byte backup restore. Record completion gaps precisely and update PR64.

Preflight: Python/backend and browser files have separate owners; exact receipt/pure bundle is their shared boundary. Root data/media/CI/workflow files do not overlap. Entire video/original requirement stays open until actual source, tracking/measurement and temporal proof are verified; a missing-state scaffold is not completion. The user's autonomous-development instruction overrides generic process approval pauses for these reversible implementation steps.
