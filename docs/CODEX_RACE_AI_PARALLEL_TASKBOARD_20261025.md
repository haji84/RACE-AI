# RACE-AI Codex parallel taskboard / verified work queue 2026-10-25

Parent https://github.com/haji84/RACE-AI/issues/67
Execution https://github.com/haji84/RACE-AI/issues/68
Current GitHub verified PR/CI snapshot: [CODEX_RACE_AI_GITHUB_VERIFIED_STATUS_20261025.md](CODEX_RACE_AI_GITHUB_VERIFIED_STATUS_20261025.md). Historic hashes below are not writer leases or current HEAD.
Detailed read https://github.com/haji84/RACE-AI/blob/feat/p0-offline-discovery-gate-20261022/docs/CODEX_RACE_AI_THREE_STREAM_MASTER_HANDOFF_20261025.md

**This is an initial work queue, NOT a grant to merge, deploy, scrape or bill. Codex must re-fetch all HEADs and replace stale check IDs when it begins.**

## 0. Current baseline evidence, NOT integrated/production proof

| source | observed pre-handoff HEAD | available CI | status |
| --- | --- | --- | --- |
| PR #69 common | bca59ebc5c7174e79d2dba027a97890f5d0d3d1 | https://github.com/haji84/RACE-AI/actions/runs/39696481097 | Four-sport synthetic E2E PASS; main NOT INTEGRATED |
| PR #71 models/odds | a3d4d011fab8773e2eab07ca83580ab345dfb708 | https://github.com/haji84/RACE-AI/actions/runs/40059352693 | UI/model contract CI success; owner iPhone / future official odds automatic E2E not accepted |
| PR #72 sources | 386d33ca57d748ed663ccd9acb34c1e5f146bc17 | https://github.com/haji84/RACE-AI/actions/runs/40087326440 | source/preview/four-sport trigger code with unit tests, AUTORACE actual trial publication not proven |
| PR #64 old K/B source | 761247bee0209e37b1af6b8885e92cad3e9260a5 | exact current checks to fetch | real K/B and history parsers exist, complex model integration unfinished |
| PR #61 53 chapters | fef68607b4773c59d6d46aa04b9e9762a42683d4 | inspect current | requirements proposal Draft, not an active main contract |

Use current GitHub HEAD/CI, not these historical SHAs, for any write.

## 1. Recommended first parallel batch (adjust dynamically)

| P0 task | owner lane | existing PR / paths | dependencies | **explicit exit test** |
| --- | --- | --- | --- | --- |
| TASK-D01: asset reuse + 3-stream spec conflicts | D reviewer/coordinator | Issue #68 and docs, all PR read-only | none | ASSET_REUSE_MATRIX and SPEC_CONFLICTS checked with real path/SHA, rights/owner decisions not guessed |
| TASK-D02: shared race IDs, first-observed/published/cutoff, cost + odds firewall | D integration | PR69 shared contract; PR71/72 adapter proposals only | TASK-D01 | source timestamp/test; sample_n missing test; odds/result input fails on every model; no data leaking |
| TASK-A01: AUTORACE trial actual race page parser | A sources PR72 | race_ai/autorace_official_trial_adapter.py, tests | legal source format and use-purpose review | one REAL active race, pre/post official observed source with actual vehicle/trial numeric, no cancel/banner false positive |
| TASK-A02: JRA published bodyweight source proof | A subworker PR72 | scripts/p0_jra_kyoto12_charset_audit_20261024.py and proposed newer official JRA race adapter | source right, actual future meet | same day JRA horse ID and bodyweight before/after observed; paddock independent |
| TASK-A03: KEIRIN rider-introduction/lines | A subworker PR72 | race_ai/four_sport_presentation_trigger.py and official provider discovery | source medium/rights | true race-ID selected rider introduction before/after, no hallucinated official line |
| TASK-B01: owner-only odds/D1/Safari audit | B odds PR71 | workers/odds_feed_worker.mjs, web/full-odds.*, D1 read-only | Cloudflare settings READ-ONLY & UI access | owner authenticates and sees 120 real odds, 3x 60s actual client reload with timestamps, no Access bypass |
| TASK-B02: legal low-cost odds ingest under review | B odds PR71 | race_ai/odds_refresh_plan.py and ingestion worker | provider/usage approved, avoid Browser Run 429 | future 1R upstream genuine odds→D1 SHA readback→Safari; still NO_BET, quota 0 yen |
| TASK-C01: PR64 real K/form+PR71 comprehensive scenarios | C model PR71 with PR72 read-only | model suite/input adapters, model reasons/fixtures | D02 and legal sources | 1 future authorized all-boat feature snapshot, original model IDs and coefficients unchanged, all120+Top8 separately |
| TASK-C02: immutable independent freeze/result PDCA | C+ D | PR69/71 freeze receipt, official revision and UI | C01 and exact source cutoff/receipt | 1 real future race external readback before cutoff, independently trusted receipt, official result/revisions, Hit@8 unbiased |
| TASK-D03: integration, independent AI09 and owner iPhone | D reviewer/integrator | Issue #68; checks, PRs; no whole stack merge | A/B/C independent slices | independent review evidence, required actual GitHub APPROVED, main protected, optional minimal approved integration, rollback/device proofs |

Tasks with unknown source usage rights are allowed for code/fixture/schema tests only, not live automated polling/long-term source storage. "Owner iPhone required" must have a specific step and expected evidence, not an invented device run. A/B/C tasks can begin in parallel once D01/D02 contracts and locks are specified; D reviews can proceed throughout.

## 2. Existing odds scenario differences to resolve (do not silently choose)

- **Model trigger**: event published and observed (fixed owner decision; not T-10).
- **Formal Top8 user visibility**: PR71 has T-10 lead requirement. If first exhibition appears later, timing is genuinely unmet; no backdating.
- **Actual full-odds refresh window**: PR71 existing T-60, user discussed T-15 or T-10 to protect free capacity. FINAL OWNER CHOICE UNCERTAIN. Build scenario table and read cloud account total usage; do not commit a new operative setting before review.
- **Economic evaluation post-freeze only**: source odds must not enter forecast training/feature selection or Top8 picks.
- **Financial**: Cloudflare Free account also has other projects; old estimation cannot assume remaining unused 100%. Actual Worker/D1/browser runtimes and 429s need read-only evidence before any nationwide roll-out.
- **Data rights**: open official webpages do not grant all purposes or a right to redistribute raw tables; authorizations are source/purpose specific.

## 3. Owner Human Gate escalation list (smallest requested action first)

1. If live source-rights confirmation is unavailable: supply exact source-specific agreement/terms or authorized access, NOT identity tokens in chat/GitHub. Reject blanket "everyone can view" as an automated download license.
2. If iPhone Safari true-device capture unavailable: provide owner-only read-only UI testing steps for Access login, 120/120 display, time stamps and 3 consecutive 60-second client reloads. Require actual observed results.
3. If another GitHub reviewer credential/independent AI09 instance unavailable: keep Draft, no self-APPROVED.
4. If planned deployment/paid Plan/Worker Access/Permissions/D1 migration changes needed: give precise scope/cost/security risk for explicit Owner authorization, NOT blanket permission.
5. If official T-10 forecast vs presentation publication causes a conflict, report actual times and preserve both facts before proposing a revised versioned policy.

## 4. Running work loop and restart record

Each bounded task update in Issue #68 must include exactly these columns: Task ID, lane/worker, current repo/PR/head_sha, AllowedPaths, source rights/policy status, expected result and source date, test and CI URL, independent reviewer run ID, actual evidence classification, UNKNOWN/BLOCKED reason, next smallest code change, next required Owner Gate.

Do not create a NEW PR for every CI failure or agent correction. Prefer updating the existing correct Draft PR after exclusive serialized branch HEAD check. If writer lock/atomic lease is not implementable, disable parallel PR writer operations and integrate patches sequentially. Identical failed method three times means replan, not endlessly repeat.

No task becomes COMPLETED by plan files, successful Github Actions with synthetic fixtures, or undocumented model assertions. Only concrete specified acceptance evidence counts.

---

# Active parallel taskboard — 2026-10-25

Integrator D is the only GitHub writer. Existing PR72 and PR71 remain authoritative. Separate managed worktrees protect the dirty original checkout and PR70 work. No force push/rebase, new PR, source acquisition, cloud write, public deploy, Human Gate change or model coefficient rewrite.

|Role|Agent|Base and AllowedPaths|State / acceptance|
|---|---|---|---|
|A publication|race25_source_audit|PR72 96afca65; publication module, tests and narrow contract doc|Explicit V2 implemented;31 focused tests PASS, separate captures and legacy recovery hold. Final review/CI recorded in Issue68.|
|B private odds|race25_odds_audit|PR71 a3d4d01; full-odds source, embedded asset, tests|Repaired in PR71 head8f19d0af; CI40122497586 Node66/Python229 PASS. Separate technical review no important findings. Deployed/device still unverified; usage403 UNKNOWN.|
|C models/PDCA|race25_model_audit|PR72 96afca65; new model_suite_settlement module/tests/script|Payload-bound adapter implemented; version/source-pin declaration gap independently reproduced and repaired. Actual pinned4sport x4family IN_MEMORY synthetic integration PASS. Persisted horse JSON still held.|
|D integration/QA|root|Docs/taskboard, offline workflow, pinned integration verification|Initial/B update on #68; original294/13missing-reference skips preserved. Reference-complete explicitvenv Python338/0skip PASS; independent final review and exact-head CI next.|

Initial live refs: main8bb7d69; PR61fef6860, PR64761247b, PR65989ffff, PR69bca59eb, PR71a3d4d01, PR7296afca65. Their full SHAs and CI runs are in the current #68 restart comment. PR71 merge-base with PR72 is070907dd335f1e0d64d31b49c2bb799e54010be3; do not assume both contain current PR69.

Before each branch mutation D acquires an exclusive local per-PR lock, checks expected remote SHA and protected workflow settings, then uses only ordinary fast-forward push. A/B/C return patches/tests; they cannot push. A changed remote head causes review/replan, not overwrite. Independent code reviewer cannot author the reviewed slice. Formal GitHub approval remains a separate gate.

Next external gates: permitted real participant/publication/feature data and cutoff, independent immutable future freeze/results, actual owner iPhone acceptance and deployed-code match, account-wide usage evidence, authorized independent GitHub review/main integration. No claim of completion or post-session background operation.

## Follow-up local transport unit

The first unit closed at PR71 8f19d0af / PR72 97c5c101 with CI40122497586 and40123289747 success, independent technical review and254-file byte/restore audit. Those records and the original limitation remain historical evidence.

C authored a separate opt-in typed private-delivery codec, independently designed and reviewed. An oversized-string pre-allocation finding was reproduced and repaired before commit. PR71 source pin ebe93f13062cf0461b81b924a5dc0482ada37b56 retains old producer/writer/CLI/model/hash/receipt code unchanged. D joins its temporary-file roundtrip to the unchanged PR72 binding/settlement, retaining all4 legacy sorted-JSON rejections and identical original model hashes/full denominators. The18-horse fixture fits4MiB; self-consistent checksums are not producer or time authentication. Exact-head CI and current pushed refs are recorded separately in Issue68 after verification; this document grants no external acceptance.

Owner action already requested: inspect Cloudflare's current plan/account-wide usage and remaining free capacity. Existing usage reader403 remains UNKNOWN; do not repeat or expand permissions. No corrected UI deployment until the concrete scoped gate, followed by actual owner iPhone Safari120-values/60sec x3 acceptance. Other real-source/freeze/results/main/forward98% gates remain open.

## Owner steering and source-readiness repair

The owner subsequently instructed: defer cost verification and finish development first. Account-wide cost/usage remains UNKNOWN but does not block local/offline work. External paid/cloud/security/source-purpose/main gates remain in force. No repeated usage403 or cloud mutation is needed for this repair.

PR72 was safely fast-forwarded to another writer's `2a99473c4755932e2d395b9e785be4f4835aef99` (one explicitly unadmitted postrace Mikuni7 audit); PR71 remains `ebe93f13062cf0461b81b924a5dc0482ada37b56`. Root is sole PR72 writer. A identified false readiness counts and the missing raw-preview join; D separate nonauthor accepted the bounded design with PENDING/PARTIAL/range cautions; root implements module/tests/contract/plan/taskboard. C audits the next durable advanced-delivery/recovery integration read-only. B's cost/deploy lane is deferred.

The repair preserves numeric candidates versus temporal evidence versus admission0, keeps F/L nonnumeric, binds raw PR64 preview race/cutoff/participants, and explicitly evaluates only the legacy two-model contract. FULL75 and existing B18 unadmitted mappings remain separate. Local reference-complete regression passed349 tests without failures/skips before independent final review; final exact-head CI/review/restore evidence is recorded separately on Issue68. This is code validation, not a real future prediction or device/production acceptance.

Independent review then found four additional gaps (invalid/aliased sample count, extra history fields, ignored explicit preview time claims, and wrong-JST-day cutoff). Original failures were retained and each repair was tested. Final local regression353/0skip; independent38 targeted tests plus25 adversarial cases passed with no unresolved important finding. The exact-head cloud CI and new-unit backup are subsequent evidence, not asserted by this pre-commit record.

## Durable advanced synthetic integration

The readiness unit closed at8e23bc49: CI40156008773/job121057451114 SUCCESS353/0skip, independent review, saved-source retrospective replay and30-payload delta restore/independent archive audit. The saved B/preview pair matches six identities, but its B SHA differs from the old forecast baseline: no old forecast lineage or new prospective success is claimed.

Next, C implemented a separate opt-in advanced-model journal after D's design criticism; root wired the fixed fictional CLI and existing CI. It calls unchanged pinned PR71 delivery/codec and PR72 binding/anchor/settlement. Complete eight-race manifests, early-cutoff ordering, atomic original transport+four local plans or NO_FORECAST, real process crashes/concurrent first creation, committed replay, result corrections and full denominators are executable. No old SyntheticJournal, model coefficient, default writer, live provider or external receipt contract changes.

Independent review found typed-equality retry/replay gaps, foreign-database initialization and date/cutoff inconsistency. C preserved REDs and repaired these, including atomic schema/application identity before any target schema change. Author29 focused tests passed81.636s; parent complete regression382/0skip passed100.552s. Separate reviewer10 repaired tests plus9 adversarial cases passed, and the sole timed final CLI passed80.396s with original wire identity,4deliveries/4missing jobs,16local plans/0external verified freezes and9result revisions. These local timings do not predict hosted-runner performance. Exact-head CI and new-unit restore proof follow on Issue68 after push.

Source rights and complete legal FULL inputs, actual future external freeze and official correction history, owner Safari remaining acceptance, formal review/main integration and prospective98% remain unmet. Cost verification is deferred, rather than a blocker for these offline units. Existing GitHub PR/CI validation continues; no new paid service, Cloudflare/Vercel deployment or resource mutation, provider acquisition, operational schedule activation or main merge is included.

## Owner priority: real-input execution before device/account acceptance

Owner now explicitly defers both iPhone real-device acceptance and cost checks.
Their position is final acceptance; they do not block other code or lawful
real-input work. Refreshed PR61/64/65/69/71/72 and Issue67/68 still match the
last recorded heads; PR72 begins this slice at45821b151af2536aea6545b16f89ffcd9cbddce0.
The completed386-test CI is retained, not rerun as unchanged work.

A audited existing actual source records and their genuine prior owner scopes.
Those facts remain allowed within their scopes; the found real bundles do not
contain a complete FULL75 normalized input or a prospective external freeze.
C implements only a separate private prepare_case/load_case checkpoint using
the original pinned models/codec, persist=True purpose checks and independent
input/cutoff/roster/private-path gates. Root implements the bounded read-only
known-commit GitHub witness resolver and their integration. D is a nonauthor
design/code reviewer; A independently inspects actual intake and backup.
Root is the sole GitHub writer. No synthetic journal, original model, default
writer or old nonce is changed. No source re-acquisition is part of this slice.

These APIs can prepare real admitted input and adopt an independently reported
pre-cutoff fingerprint without giving the resolver any write capability.
Prepared plans are not publication attempts. Before any later mutating
orchestration, durable attempt consumption and uncertain-write recovery remain
mandatory. Private local payload retention is not private cloud retention.
Full-field actual input, source/cutoff/publication authenticity and genuine
future external storage/results still determine actual E2E acceptance.

## Follow-on: consumed submission intent before external writes

Prior unit closed at72b8c94d8a4b590e426d4909ce33621a86493090:
CI40185829951/job121146287870,441PASS/0skip, separate D/A reviews and
169-payload byte-restored packet independently audited804 checks. Actual
retained156-ledger input returned NO_FORECAST, not a future prediction.

Next bounded spec is P0_PERMISSIONED_CASE_SUBMISSION_20261025.md. C owns only
the new permissioned_case_submission module/test; D is its nonauthor design
and code reviewer. Root owns integration/CI/docs and is sole PR72 Git writer;
A audits evidence/backup. Every previously reviewed case/witness/model byte,
old synthetic journal, original dirty checkout and held33 remain unchanged.
No actual submission/source/deploy occurs in this implementation slice.
Local intent recovery cannot prove cloned-store safety, global exactly-once,
multi-runner persistence or protected whole-payload cloud retention.

## Follow-on: whole-case private retention handoff

The public-intent unit closed at770a620d8e73de0bb7d9d09e8bb52e8282ddaa93,
CI40189412598/job121157016710:465PASS/71.606s/0skip. Local465/90.801s,
separate24tests+11probes and739-check independent151-payload restore audit are
recorded in Issue68 comment6397235263. No actual source/forecast/cloud operation.

Next spec P0_PRIVATE_WIRE_RETENTION_20261025.md adds two local whole-wire
request/supplied-evidence APIs. C owns only new module/tests; D is a nonauthor
reviewer; root owns CLI/workflow/docs and sole PR72 writes; A audits integration
and bytes. The separately admitted PRE_PUBLIC_BASE_ONLY binding is prospective
and acyclic, not current Race28 dispatch enforcement or model1's storage intent.
All frozen models/codec, existing case/submission APIs and held33 are retained.
No writer, transport, duplicate registry, resource or security change is added.
Actual private backend/coordinator and lawful full-input/future E2E remain open;
device/cost acceptance stays deferred rather than blocking local implementation.

## Repair: UTC ordering in historical submission recovery

Whole-wire handoff closed at2e85ab2f351679f3d9fe153817c85636069b01a9:
CI40192399033/job121165986539,488PASS/90.895s/0skip; local488/97.723s.
Separate23tests+15probes and839-check independent146-payload restore audit
are recorded in Issue68 comment6397625874. Actual future forecasts remain0.

Goal: repair the inherited submission clock's comparison across a DST fold.
The prior helper stored raw aware wall times; with the same ZoneInfo object,
UTC rollback could pass historical recovery's entry-to-reopen highwater and
genuine UTC advance could fail. This is a local clock-order contract defect,
not evidence of duplicate PUT, an authentic external witness or an old503 cause.

Done requires normalizing valid samples to UTC before comparison/storage,
both fold directions through the public historical recovery API, rollback
before any reader/evidence mutation, and preserved sanitized invalid clocks,
intent barrier/noACK/remaining-model state. Existing UTC behavior and all
case/schema/transport/model contracts stay fixed. C owns only the existing
submission module/test; root owns this taskboard and serialized PR72 writes;
D is a nonauthor reviewer; A audits new evidence/restore. Independent design
criticism is preserved before implementation in race30-clock-design-criticism.

Run the focused regressions, one final reference-complete local suite, exact
new-head hosted CI and bounded independent review/restore audit. No new engine,
source collection, cloud/security commitment or operational schedule is added.
Lawful complete prospective real input, protected external original retention
and shared coordinator, actual results, formal review/main and98% remain open.
Owner's device/cost deferral does not postpone this code repair.

## Next dependency: fixed maximum-eight case profiles

Race30 closed at f155686cd7a425eab31e91e16657e2cd396114a9,
CI40193619395/job121169660000:491PASS/86.594s/0skip. Race31 PR71 closed
at db075c203704d2b30df5742ce8458a43932696a4, UbuntuCI40195398220:
Python251/14.606s and Node66 PASS. Windows251 retains two inherited POSIX0600
assertion failures; neither WindowsfullPASS nor actual ACL proof is claimed.

Race32 Goal/Done: P0_FIXED_MODEL_CASE_PROFILES_20261025.md. Root owns fixed
profile/case/binding/settlement/submission integration and sole PR72 writes;
C owns only isolated runtime/worker/tests, D independently critiques, A checks
exact public reference/legacy/packet bytes. No new real input is invented.
V1/ebe remains unchanged; V2/db075 explicit new preparation uses verified bytes
in a bounded secret-free child, then original typed wire and immutable case.
Existing committed cases replay without inference/renewal or pin replacement.
An explicit full-window callback is required for V2; mutable grant dates do not
authenticate it. No API default grants source/private/cloud/release permission.
Actual full input/provenance, external protected whole-payload storage/shared
coordination, official results and formal main/98% acceptance remain open.

## Next dependency: durable private retention before public intents

Race32 closed at b71bb7138bd416e2cb1a222ccdb2980d62f987d7,
CI40199982391/job121188913992:525PASS/95.839s/0skip. Separate nonauthor
review,233-payload source audit1219+11 checks, late16-payload audit85 checks
and Issue68 comment6398812499 are complete. The original review wording P3
and separate correction remain preserved. Cross-runtime wire SHA differences
are not numeric/byte equality or an inferred floating-point cause.

Race33 Goal/Done: P0_DURABLE_RETENTION_PREREQUISITE_20261025.md. C owns the
sole attempt owner's explicit version2 and retained APIs/focused tests; root
owns public integration/fictional CLI/workflow/docs and serialized PR72 writes;
D is the nonauthor reviewer, A audits bytes. Before core changes, an original
V2/db075 case with a legacyV1 attempt/4ACK fixture was captured exactly once.
The earlier V1 fixture also remains unchanged; cached replay must never renew
model inference, source authority, clock or transport.

This is local callback-qualified coordinator enforcement, not a chosen/deployed
private backend or authenticated cloud receipt. Original typed wire precedes
private E, E commits before public intent, intent commits before PUT. Unknown
writes retain the permanent barrier; GET-only recovery cannot ACK or resend.
No paid/cloud/security/main/schedule operation, new source retrieval, inherited
held33 retry, retrospective prediction or real performance claim is authorized
by this code slice. Device/cost acceptance remains later as Owner requested.

## Next dependency: consume a private action in the same attempt owner

Race33 closed at8c813eedab0cc534a0f1388dfde147761a88d155,
CI40205914841/job121206685147:551PASS/131.390s/0skip. Its source and
delivery audits and Issue68 comment6399483760 are separate completed evidence.
Race34 PR71 closed at9aeb2b425de9d05a44cb31f72a242a5111ada80a,
CI40210790393/job121221363066:Node88/Python251PASS/9.655s/0skip.
That unit implements the local native vault; it does not itself enforce
cross-call unknown-write retry prevention or authenticate a cloud receipt.

Race35 Goal/Done: P0_PRIVATE_RETENTION_ACTION_V3_20261026.md. The explicit
prospective PRIVATE_ACTION_V3 adds one immutable P row to the SAME C/E/public
attempt owner. Only the invocation whose P COMMIT returned normally may call
the explicitly admitted local create seam once. Existing or uncertain P is
consumed, including zero destination writes; lost-return bootstrap and exact
read recovery cannot resend, initialize storage, ACK or release publicly.
Final deterministic owner identity and UTC checks follow arbitrary gates.
Original V1/V2 profiles, model pins, saved wires and ACK replay stay unchanged.

C owns the two existing submission modules and the new private-action module/
focused tests. Root owns the TEST-ONLY fixed Node bridge, native integration,
four-sport fictional CLI, fixed reference manifest, workflow and serialized
PR72 writes. D is a nonauthor reviewer; A audits bounded bridge/capture and
evidence bytes. The exact design review precedes implementation. Meaningful
failures and their repairs remain separate; implementation acceptance, final
full tests, exact-head automatic CI and delivery audit are separate gates.

This dependency proves local byte/control-flow behavior only. Actual lawful
complete prospective model input/provenance, independently protected whole
payload retention/receipt and shared sole assignment for that SAME case are
still absent. Missing genuine E means public intents/HTTP0. No extra local
simulation may be labelled a real forecast, real receipt,98% acceptance or
formal completion. Device/account/cost acceptance stays deferred by Owner;
cloud/security/schedule/main and held33 stop constraints remain unchanged.

## Next dependency: measured K course/ST history without invented features

Race35 closed at e7cf1a41da94fd295508bc080fd4240ecff18a67. Local590PASS/
187.798s and automatic CI40215415264/job121235381052:590PASS/107.124s,
zero failures/skips, are separate from source774-check and late104-check
independent byte audits. Issue68 comment6400933989 records the unit. Native
local retention is not authenticated cloud storage or a real forecast.
Cross-runtime boat/keirin wire hashes differ; equality/numerical equivalence
and a cause were not established. Saved original fixture profiles/owners and
their limits remain recorded separately.

Owner did not know a data location. A/C traced the existing official B/K/
beforeinfo route instead of requiring Owner expertise or repeat approval.
Some mandatory FULL latent measurements have no defined source transform;
finding another folder cannot supply them. Do not invent these values.

Race36 Goal/Done: P0_BOAT_OBSERVED_COURSE_HISTORY_20261026.md. C owns only
the new measured history module and focused tests, root owns this narrow
integration/spec/plan/CI filters and serialized PR72 writes, D is the nonauthor
design/code reviewer. A prepares a separately reviewed private one-shot caller.
Reuse actual pinned PR64 statistics; preserve lane/course, F/L/MISSING/ABSENT,
samples, whole revisions, unknown publication and explicit withheld order.
No new authority gate, journal, model or collector workflow is introduced.

Known aggregate source evidence covers K01..23 and B24. NEW K24 is a distinct
candidate for one bounded factual RAM parse after exact caller review and
one-attempt admission. K25 is not eligible under the strict prior-UTC-day
guard until09:00JST26; no clock or weaker-transport bypass. A measurement cohort
from an older race is not a future race roster, and unknown publication cannot
enter qualified as-of statistics. Later actual source outcome/CI/review stays
separate from this implementation-stage plan.

Full prospective model input/retention/receipt, all-sport production loop,
future results/PDCA/98% and formal main acceptance remain incomplete. A new
model scoring/required-feature contract needs a separate concrete Owner/design
decision. Device/account/cost acceptance remains deferred. Original root,
prior forecasts, held33 STOP and public/cloud/security restrictions are kept.

## Race37 / 2026-10-27: Owner-approved missing-aware pair

Owner explicitly authorized autonomous development of the coverage-first separate
experiment after discussing missing data and same-race comparison. This supersedes
Race36's pending model-design decision for this candidate only. FULL75 and original
four models remain unchanged. Root alone integrates PR71 and PR72 serially.

PR71 adds two untrained observed-pair models with raw units, explicit missing
states, fixed weights, complete 120-trifecta scores/Top8 and utility completion
bounds. No discriminatory utility is separately labelled; output coverage is not
informative coverage. Independent review found output-spec aliasing and conflicting
same-window history claims; both have separate RED/GREEN evidence and are repaired.

PR72 adds a strict parsed-B projection and a replayed same-race/same-stage
comparison. Missing output stays in the claimed-evaluable denominator, both models
use the same actual supplied result revision, and P0/P1 is a separate information
comparison. Reordered model dictionaries and non-BOAT result lanes were independently
reproduced and fixed. The actual pinned model is exercised through bridge and
comparison on four fictional complete/partial/all-missing/no-output scenarios.

One fresh B27 archive is the bounded real-input candidate, using the existing
owner-attested facts scope, exact source/code pins and an exclusive attempt marker.
Raw archive/text and full per-racer model input/output stay RAM-only; hashes and
counts survive. A completed computation will be REAL_INPUT_RESEARCH_INFERENCE,
not an externally frozen prediction, retained private wire or future scored pair.
Actual source outcome, exact-head automatic CI and final independent reviews are
reported separately in Issue68; no planned run here is represented as a success.

Formal prospective E2E still requires current roster/final cutoff, genuine
availability/producer binding, protected immutable retention and external witness.
Research flags remain false, formal Hit@8_all null, 98% unproven. Device/account
cost acceptance stays deferred; no new paid/cloud/scheduled resources or self-
approved main merge. Held33, original dirty worktree and old source evidence stay intact.

## Race39–40 / 2026-10-27: Same-cohort evaluation and retained real evidence

Owner requested historical data preparation, fair evaluation of every model on
the same races/information conditions, and verification on today's races. The
source-only inventory retains19 model IDs, including numerical aliases and models
without usable inputs/artifacts; an inventory slot does not establish execution.

Race39's generic plan/seal/journal/CLI is committed on PR72 at
`b78a889bab7d098532e531dd44aba3ec2636af8e`. CI40443977101 passed the679-test
Linux regression and48 focused tests on both Windows/Linux. The separate train-only
API on PR71 at `6f75fa9f98beb5a6d8f190694e96695d5ffb31be` passed CI40442057767.
Training does not inspect the final evaluation labels. These are code checks,
not evidence of19 real models or a98% hit rate.

The corrected private B27 retention contains168 races×19 IDs,524 forecasts from
four engines on131 races and2668 missing slots. Original capture/generation/readback
claims are preserved. A hash-only GitHub witness predates130 planned cutoffs and
is late for one; provider publication/final-cutoff/withdrawal authentication remains
unproven. Two newly retained K25/K26 archives contain310 complete prior races and
1860 rows, plus one quarantined incomplete race. Current-day participants have
at most four retained prior observations; these archives do not fill FULL75.

Two independently admitted result batches observed nine new races: three normal
results (all four running engines missed each), one pending, three unavailable or
invalid with causes unproven, and two cutoff differences requiring review. The
other159 races are unobserved by those batches. Source attempts total12GET
(B1+K2+result3+result6), with no retries or prediction regeneration. The private
Race39 packet has285 payload files; full source/member/restored hashes, CRC and
manifests were independently audited. Old failures and the held33 remain unchanged.

Race40 Goal/Done is `RETAINED_PREDICTION_AUDIT_20261027.md`. C owns the new
retained adapter, arithmetic, CLI and fictional tests; D reviews independently;
A audits exact real files and report arithmetic; root alone integrates docs,
workflow, real journal execution, CI and private backup. The retained path is
development-only, with a current import time separate from the original clocks,
and reserves shared race exposure before a lazy, hash-pinned result reader.
It must not manufacture a backdated generic plan or classify known outcomes as
untouched final data. The five-command real connection completed with a current
04:31:25UTC import, followed by3-label observe,6-label append and prior/latest
recovery. An independent stdlib audit checked all3192 rows of both reports and
all524 unchanged forecasts. Exact-head CI/backup acceptance is recorded separately
after execution. Other-sport real coverage, missing15 engines, sufficient historical
windows, genuine prospective all-race evidence, formal review/main acceptance and
98% remain incomplete. Device and account-cost confirmation remain deferred.

## Race41 / 2026-10-28: Measured single-day history in existing research inputs

Fresh starting heads were PR72 `5608ab9c60c6ad48d3aa1978894f3215f4a9c1e9`,
PR71 `6f75fa9f98beb5a6d8f190694e96695d5ffb31be`, and main
`8bb7d69f9c8fb302055bc9e2609903d1e8f73e4b`. Existing completed checks were
read, not rerun. Root owns the small adapter/test/spec/plan and existing CI
integration on PR72; A prepares private source evidence and D reviews independently.

`P0_CAPTURED_HISTORY_BRIDGE_20261028.md` defines the separate pure single-K-day
adapter. It reuses B identity/rate validation and K structural validation, retains
unknown publication as a capture claim, and supplies real finish/ST means and
separate denominators to unchanged pairwise models. Source/row membership and
registration are bound; omitted complete races change the window identity without
claiming whole-day completeness. Course/exhibition values remain unavailable.
The old publication-qualified history gate, model IDs/weights and seals are unchanged.

Independent design criticism resolved membership and retrospective-clock ambiguity.
Independent code review found Unicode identity and signed-zero duplicate defects;
root reproduced five failing subcases and repaired both. Final16 focused tests and
the reference-complete728-test local regression passed with no skips. The first
integration run lacked three local pinned reference files; preparation from existing
Git objects resolved that environment issue without downloads or product changes.
Exact new-head Windows/Linux CI is recorded separately after push, not presumed here.

Retained B27/K26 data connected in a separate development replay at actual
2026-10-28T08:48:52Z, with declared information-as-of2026-10-27T03:00:00Z.
All168 races and3192 registry slots remain visible:127 races produced two existing
pairwise-model outputs each;41 were already closed at the declared information
context. Other17 model IDs are explicitly not executed in this replay; they are
not old forecasts transplanted into a new comparison. It read no target results
and made zero source requests. No hit-rate, historical generation or genuine
pre-cutoff claim follows. An initial registry guard rejected the separate synthetic
control before reservation/inference; that original failure remains preserved.

A separately reviewed current-day caller may use fresh B28 plus retained K26 and
actual clocks once admitted. Preparation is not source success or a saved forecast.
All19 true model IDs, missing inputs/artifacts for15 engines, all-sport real coverage,
prospective scientific validation, formal review/main acceptance and98% remain unmet.
Device/account-cost checks stay deferred; held33 and original dirty work remain intact.
