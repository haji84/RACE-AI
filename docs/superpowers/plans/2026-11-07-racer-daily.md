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
Interfaces: RaceRacerDaily.load/get/status/period; strict identity-bound daily cards, explicit period/source gaps/ST counts; no mutation of saved inputs. Same-origin JSON fetch; offline export embeds a local snapshot or explicit unavailable state.
- [x] Browser/API tests RED on sparse athletes and unavailable/stale/synthetic/partial data; add daily metrics and six-course cards.
- [x] Add fixed asset/extra JSON allowlists, preserve daily data across UI/forecast publications, verify offline CSP and legacy migration. Run existing UI/crypto/profile/package checks; commit.

## Task 4: review, first production run and daily enablement
- [ ] Fresh read-only whole-change review; one TDD fix pass for material findings.
- [ ] Preserve concurrent source updates, publish UI on existing Pages with unchanged original/cipher/portrait files.
- [ ] Trigger first authorized real initialization on GitHub Actions, verify encrypted retention + live daily JSON + real populated card.
- [ ] Open and normally integrate the scheduler-only main PR after required CI, with pinned implementation SHA; no bypass. Confirm scheduler registration and first real run.
- [ ] Record source coverage, counts and actual deployment evidence; finish plan.
