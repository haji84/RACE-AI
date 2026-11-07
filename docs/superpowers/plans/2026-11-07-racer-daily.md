# Racer daily statistics implementation

User authorization: latest「接続して」selects the previously described daily official results → athlete/course aggregation → card update flow. Existing publication approval persists. Native inline execution; one fresh whole-change review at end.
Spec: docs/superpowers/specs/2026-11-07-racer-daily-design.md
Base: 5eb7bec61f9892f80727b742d75056641da9d7d4

Global constraints: GitHub only, no new keys/providers/charges/permission changes. Preserve original forecasts, ciphertext, old state namespaces and all1669 approved portraits. No raw result documents/SQLite/keys in public trees or logs. Main integration contains only the scheduler workflow and respects existing protection/CI.

## Review Focus
- Daily aggregation counts actual starts including F/L/disqualification, excludes confirmed absences, and never substitutes frame for unknown actual course.
- Source gaps and partial venues are explicit. Historical target races do not receive later information as prediction inputs.
- Bootstrap uses authenticated retained monthly archives; the daily snapshot cannot reset after missing/corrupt state or rollback revisions.
- Only derived aggregate JSON is public. Daily publication cannot overwrite current UI/forecast ciphertext; ordinary publication cannot reset daily statistics.
- Protected main gets only a pinned scheduler, no unrelated PR71 work; exact deployed and real first-run evidence precede success claims.

## Task 1: daily aggregate and durable encrypted state
Interfaces: DailyStore.record(day,raw,captured_at), catalogue(roster,as_of,days=90), serialize/restore; append-only transfer namespace and authenticated monthly bootstrap.
- [x] Tests RED for actual K parsing, rate denominators/absences/ST samples, gaps/date boundaries, duplicate/corrected archives, snapshot tamper/rollback.
- [x] Implement bounded catalogue and encrypted checkpoint/publication using existing primitives. Run relevant Python tests; commit.

## Task 2: bounded collector and scheduled job
Interfaces: refresh(repo,private_dir,now,initialize=False) restores authenticated state, imports retained recent months on initialization, requests at most7 canonical daily K archives, saves state, emits aggregate release and bounded counts. Publish only one fixed daily JSON path on gh-pages, preserving every other blob.
- [x] Tests RED for bounded transport, 404/429, missing state, duplicate/no-source changes, independent state/public CAS and preserved trees.
- [x] Implement CLI/workflow with existing owner secret, no plaintext artifacts, fixed-source pin; validate locally and prepare first real Actions run.

## Task 3: card reference and distribution
Interfaces: RaceRacerDaily.load/get/status/period; strict identity-bound daily cards, explicit period/source gaps/ST counts; no mutation of saved inputs. Production fetches the fixed gh-pages JSON through the existing GitHub raw CSP allowlist (GITHUB_TOKEN pushes do not trigger Pages builds); local uses same-origin JSON. Offline export embeds a local snapshot or explicit unavailable state.
- [x] Browser/API tests RED on sparse athletes and unavailable/stale/synthetic/partial data; add daily metrics and six-course cards.
- [x] Add fixed asset/extra JSON allowlists, preserve daily data across UI/forecast publications, verify offline CSP and legacy migration. Run existing UI/crypto/profile/package checks; commit.

## Task 4: review, first production run and daily enablement
- [x] Fresh read-only whole-change review; one TDD fix pass for material findings. Real404 retry without a timestamp, GitHub raw daily delivery and full reachable-history rollback protection each reproduced RED and corrected. Final Python97/97, Node97/97, explorer18groups and crypto/offline browser GREEN. No review re-dispatch.
- [x] Preserve concurrent source updates, publish UI on existing Pages with unchanged original/cipher/portrait files. Pagesf4cea73e changed4presentation assets; exact HTTP readback and7cipher/54image preservation passed. Concurrent video and seller retirement work was merged normally and retained.
- [x] Trigger first authorized real initialization on GitHub Actions, verify encrypted retention + live daily JSON + real populated card. Run42358904704 restored88authenticated days, confirmed4official files and added1day. All1669catalogue entries published; actual aggregate metrics and sparse-course safeguards passed on6athletes×6courses×3screen widths.
- [x] Open and normally integrate the scheduler-only main PR after required CI, with pinned implementation SHA; no bypass. PR85 merged as6ecf770f after requiredunit and all applicable checks succeeded; main remains protected. Runtimecfa61b38ed05156e23b012cacd802ec922b29b90; main workflow cron20 21 * * * (06:20 JST) verified. Main dispatch42362151647 restored generation1 without initialization, saved generation2 and verified the new public SHA successfully.
- [x] Record source coverage, counts and actual deployment evidence; finish plan. Evidence: docs/evidence/2026-11-07/racer-daily-verification.json. Final related Python99/99 and Node97/97 GREEN; actual public browser proof after the main run GREEN. 2026-08-09–11-06:89of90days usable,2026-09-14 missing,0partial days. Initial runner failures and the tested filtered write fix are recorded in the spec; no key/reset/provider/permission change or raw-source publication.
