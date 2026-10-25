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
