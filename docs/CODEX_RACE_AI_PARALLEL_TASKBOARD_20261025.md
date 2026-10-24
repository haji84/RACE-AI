# RACE-AI Codex parallel taskboard / verified work queue 2026-10-25

Parent https://github.com/haji84/RACE-AI/issues/67
Execution https://github.com/haji84/RACE-AI/issues/68
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
