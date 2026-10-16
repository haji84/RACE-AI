# RACE AI accepted handover requirements

This records the user's 2026-10-15 chapters1–53 as development requirements, not evidence of completion. The repeated chapters1–51 in the message are one specification. Supplied chapter52 jumps from52.9.2 to52.18:52.10–52.17 were not supplied and are not invented here. No requirement is dropped because its implementation is difficult.

## Scope and release gates

- Current JST official race information without manual file registration; all24 standard boat venues (01–24) and1R–12R where scheduled; names, racer registrations, motors, meeting identity, source/time must agree.
- Responsive phone/PC home, all-races, details, tickets, performance, research, settings from8supplied images. White/pale blue, navy/blue/teal, desktop left navigation and right rail, mobile bottom navigation. Reference numbers, faces, odds and ratings are design-only, never factual input.
- Boat racing first. Other sports use separate participant/rules/models and visibly unfinished states.120ordered triples applies only to6boats. Automatic wagering/payment is excluded.
- General release requires actual functionality, source rights, independent quality/security checks, recovery, monitoring, cost evidence, terms/privacy and final user decision. Staged release may expose only verified scope; advanced incomplete features stay declared incomplete.

## Data/time/API/storage contract

- Worker acquisition, normalization, validation, storage, API and display are separate. Browser does not harvest upstream sites. /api/today uses current JST day and exact race-ai/day/YYYY-MM-DD.json; SDK private access, exact keys, no accidental suffix, SHA readback and concurrency/version control must be demonstrated.
- Retain source-observed/available/normalized/published timestamps, provider URLs/hashes, original versions and corrections. Separate available/partial/pending/unavailable/stale/no_event/cancelled/error. no_event needs positive schedule evidence; failures cannot create it. No fake fallback numbers or yesterday-as-today.
- Model race/date/venue/meet, player registration, equipment number+venue+usage period, entries/courses/exhibition/odds/weather/video/forecasts/settlement/models/users/rights/audit. Deduplicate and reconcile corrections without rewriting history.
- Private Blob serves live day data; GitHub archives only verified allowed normalized history. GitHub archive failure must not stop healthy Blob delivery. No original photos/video/secrets in public GitHub. Independent backups need measured restore proof.
- Per-type schedules and bounded retries/backoff, origin controls, deduplication, leases/idempotency, pre-publication validation and atomic/versioned switches. Costs and upstream allowed frequency constrain execution.

## Analysis and prediction

- Player actual-course5/10/20 past runs: raw and official ST series/mean/SD/median, start rank/mean, annual same-course difference, sample count, missing/excluded reasons. Frame10 remains distinct from actual-course10. Speed and stability are separate. Unobserved aggression/psychology/causes are not facts.
- Conditioned win/loss mechanisms, front-entry initiator and recipient resistance, course retention/displacement, confirmed deep inside and adaptation; sample periods/counts/courses visible. No unconfirmed event counted as confirmed.
- Motor/boat usage periods, rider/opponent/course/weather correction, maintenance/exhibition and relative motion features; measured and estimated performance kept separate.
- Exhibition start/course/times/bodyweight/tilt/parts/weather and origin-specific original exhibition; do not equate exhibition ST with race ST. Recompute a new prediction version on meaningful updates.
- Licensed private video acquisition/storage/retention/provenance/version/deletion, frame preparation/tracking/quality scores/manual truth. Calibrated relative speed/turn measures when absolute physics cannot be measured. No access restriction circumvention.
- Weather/sea/tide observations, forecasts and estimates separate. Odds per ticket/source/acquisition time, no overwrite and no later odds substituted into earlier forecasts.
- Baseline interpretable joint model and scenario simulation; for6boats calculate all120 valid distinct-lane triples, total1, coherent position marginals; recalculate combinations on absences. Special race outcomes need a separate official settlement definition.
- Forecast IDs/cutoffs/features/versions/scenarios/probabilities/odds/EV/stakes/skips saved immutably before start; later forecasts separate. Actual current race ST/entry/result/method/payout/video or post-cutoff data must not enter a pre-start forecast. Availability time matters as well as capture time.
- Separate odds/no-odds and video/no-video models; common untouched time-ordered evaluation, baselines, Brier/log loss/calibration and count/uncertainty. Sum-to1 is not prediction accuracy. No unvalidated S/A or accuracy advertising.
- Model selection/retraining/promotion require explicit rules, reproducibility, leakage checks, regressions, speed/cost and proven improvement. Explanations come from actual inputs, not invented post-hoc reasons. Preserve old model when improvement not shown; logged rollback available.

## Tickets, exact money and results

- Standard cap8; settings16/24/32. Select fewer as useful including0skip. Skip insufficient EV/reliability/data/freshness/time/budget/cancellation and explain. High odds alone do not justify high-payout recommendations.
- Budgets per race/day/week/month, max transaction and loss cap; no chasing losses. Separate proposed candidates, AI virtual purchases and actual user-confirmed purchases. Interim session-only manual accounting is not persistent multi-user service or an AI recommendation engine.
- Shared fixed-point/integer calculations: with p in[0,1], multiplier o and yen s, hit payout=s×o, expected payout=p×o×s, expected profit=expected payout−s, expected return%=p×o×100, expected profit%=(p×o−1)×100. Official confirmed payouts override estimates.
- All ticket stakes count: four¥100 tickets and¥1500 payout gives¥1100 profit,375%return. Zero effective purchase means return rate unavailable, never0%. Settled cash profit=payout+refund−gross stakes; return denominator excludes refunded stakes. Refund is recorded cash, not a hit or loss. Avoid double-counting. Official ties/special payouts/void/corrections remain separately verified.
- Allocation total and remaining budget exact; rounded percentages coherent; invalid/negative/nonfinite/missing values rejected. Purchase unit/rounding/odds precision require confirmed rules. Bound risks using mutually exclusive outcomes and uncertainty, not EV sums alone; no unverified full-budget Kelly stakes.
- Score race-hit and ticket-hit separately; exclude skips and unsettled records from settled metrics; recommended/virtual/actual ledgers separate. Preserve prediction on official result correction and recompute derived scores. Show periods/races/tickets/version/missingness.
- Required money tests cover¥100×15=¥1500,0.1×15×100=¥150,¥50EV profit,150%EVreturn;¥400/¥1500→¥1100/375%; all loss/full/partial refunds; official special results; odds refresh; budget overflow; zero/invalids; API/UI agreement.

## Accounts, safety and operations

- User preferences/budgets/purchases/accounts isolated; login persistence and admin auth/authorization/audit. Admin health covers worker/data/API/Blob/archive/models/video/rights/backup/errors/performance/cost and reports.
- Minimum privileges for signed Github JWT issuer/audience/repository/numeric identity/ref/workflow/environment and Preview-only probe; GitHub issuance, edge protection, app auth and Blob are separate evidence stages. Keep keys out of logs, URLs, responses/source; protect against injections/CSRF/SSRF/path abuse/oversize/rate abuse and manage dependencies.
- Recovery retains last valid data with stale labels, bounded retry and targeted stop. Track faults, impact and restoration. Monitored API/worker/storage/model success and latency/cost, deduplicated alerts, restore tests and rollback.
- Public age/use restrictions and source rights require authoritative confirmation. Ingest/store/internal analyze/public derivative/raw release are separate allowed/denied/approval_required/unknown decisions for each source/media. No blanket permission based on free viewing or private use.
- Phone readability/tap targets/no unintended horizontal overflow, keyboard/focus/screenreader/color contrast on PC. Actual Safari and referenced visual comparison remain separate tests from Chromium emulation.

## Evidence and continuity

Each requirement links code/test/Issue/PR/head/CI/E2E/source/UI proof/status/blocker/next action. Completion is verified usability, not line count or PR count. Five E2Es: private Blob; authorized day source→screen; real entries→probability→tickets; pre-start forecast→official result→score; licensed video→features→measured improvement.

Statuses: not-started/research/design/implementation/testing/review/live-verification/complete/external-wait/blocked. Save run/deployment/source/time/hash/screenshots and exact limitations. Refresh current state when asked, and resume from GitHub rather than chat alone. Ordinary authorized work proceeds autonomously; session lifetime and external scheduled automation remain distinct.

## Existing-spec differences

docs/BOAT_FIRST_RELEASE_PLAN.md currently describes a manual local JSON first scope and bans persistent storage. The user's new normal flow replaces that scope with automatic API data and later isolated authenticated persistence; arbitrary client storage or unverified data is not authorized by this change. Old research-only branches remain unmerged. This documentation proposal changes no runtime permissions, deployment protection, source grants or Production settings.
