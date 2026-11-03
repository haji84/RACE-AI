# Specification conflicts and decisions — 2026-10-21

## Current adopted constraints — 2026-10-25

|Conflict|Ruling|
|---|---|
|Official presentation publication versus old T-10 restriction|Begin input checks on genuine observed publication; no arbitrary ten-minute trigger window. Availability alone never grants rights or full model readiness.|
|Odds T-60 default versus owner-considered T-15/T-10|Unresolved final owner choice. Preserve T-60 and keep acquisition disabled until purpose/cadence/shared quota evidence. Separate from publication trigger and T-10 forecast-display target.|
|Timestamp-dependent replay keys versus restart idempotency|Use an explicit versioned stable publication identity; do not silently reinterpret V1 persisted hashes. Equal-time or unchanged bytes do not prove a newly published source.|
|Ordinary JSON persistence versus original typed model hashes and roster order|Keep legacy outputs/versions/hashes unchanged. Explicit opt-in typed ordered-pair transport preserves original values; plain V1 repair and implicit migration remain forbidden. Local synthetic persistence does not attest producer execution, source rights or external reception time.|
|External hash receipt versus separately supplied picks|Receipt authenticity alone does not bind independently supplied tickets. Derive picks from checked original model payload and keep every missing eligible race in each predeclared model denominator.|
|Safari interval display versus actual audit-ready receipt|Preserve each event's actual race identity; UI success alone and VM tests are not owner-device acceptance.|
|Historical D1 real odds versus future automatic ingestion|Existing four historical real races are preserved. Fresh metadata protection/read=true/ingest=false/cron0 does not prove source cadence rights, deployed SHA equality or account free allowance. Billing403 stays UNKNOWN.|
|Cost/account verification versus continued development|Owner explicitly deferred cost checking and instructed development to continue first. UNKNOWN account usage does not block local/offline implementation and its bounded existing CI. It does not authorize a new paid service, shared cloud consumption, deployment or security change.|
|Technical review versus formal main acceptance|No CodeRabbit or self-approval. Exact-head CI and separate-context technical review cannot replace independent GitHub APPROVED/Human Gates.|

These are narrow repairs of adopted contracts, not new rights, platform replacement, paid usage or deployment authorization. Earlier rows remain historical.

Authority: user instruction + Issue68 comment6315990805 + PR61 fef6860 amendments. Unconflicted 53-chapter requirements remain.

| Conflict | Decision |
|---|---|
|Boat-first/six participants vs four sports|Keep old boat engine; adapt top-three conditional calculation to N. Explicit field size; 6=120/7=210/9=504; no N! horse enumeration.|
|16/24/32 UI vs official Top8|Old UI untouched. Synthetic STANDARD_8 has exactly 8; no betting. 0 forecast represented with explicit reason.|
|Legacy market feature/trainer vs odds-free all prediction stages|Legacy offline trainer is reachable and audited, not adopted. New exact sport feature allowlist + fixed untrained model excludes market/popularity/payout/third-party/current result; sidecar outside all prediction/hash paths.|
|Old saved-before-start vs authoritative sales cutoff|New contract stores both; requires synthetic persisted clock < sales cutoff and rejects revised/stale cutoff. Real external attestation unverified.|
|Predicted-only results vs Hit@8_all|All offered/evaluable races retained, including actual missing feature. Void/nonoffered/pending are separate. Historical result corrections bind exact discovered revision.|
|Local machine vs hosted short batches|Hosted CI uses standard runners, no ZBook/environment/Secrets. No operational cron until external durable state, rights and deadline scheduling proven.|
|Vercel automatic builds vs cost control|Root and known web-root git.deploymentEnabled=false before push, documented by official Vercel configuration. No deploy command, credential, provider artifact upload or cloud integration. Existing deployments/stores not deleted or stopped by this setting. Main merge still requires gate/readback.|
|Cloudflare prior local work vs latest Actions priority|Preserve all local migration assets; do not deploy/migrate/pay. Current slice is Actions validation only; owner cloud migration/publication gate persists.|
|Technical independent agent vs owner/GORIQ review|Independent read-only technical review is evidence, not GitHub APPROVED, GORIQ AI-09 acceptance or authority to merge.|
|SQLite simulation vs production immutable truth|This unit deliberately accepts synthetic-only. Chain/triggers/transactions/backup/clock checks are tested, but local state or Actions artifacts are not the production database. Trusted external timestamps, multi-run cloud restore and continuously observed operation remain unverified.|

98% Hit@8_all is an unvalidated challenge goal. Synthetic 3/5 only tests arithmetic and excludes no real failures; it is not real accuracy, calibrated probability, improvement or a 98% feasibility claim.
