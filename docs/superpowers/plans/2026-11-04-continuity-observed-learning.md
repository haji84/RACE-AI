# Continuity and automatic fitting of existing observed model weights

## Goal and scope
Preserve the five frozen baseline models. Automatically fit versioned weights for the two existing observed-pairwise families from authenticated past input/result pairs, freeze training artifacts, shadow-predict only later races and compare against the original same-race baseline. No automatic promotion, new predictor family, task, workflow, paid resource, main merge or betting.

## Design
Retain the exact existing contrast vector and Plackett-Luce equations. Use one authenticated input per race, preferring the later P1 observation when available; never duplicate a label across P0/P1 or two models. Record training phase composition. Only coefficients with at least four informative TRAIN races change; all unsupported coefficients remain at their original values. Score future P0/P1 comparisons separately. Deterministic regularized projected gradient descent, outcome-availability-ordered train/holdout separation, explicit small-sample status. Holdout is retrospective diagnostics, not prospective accuracy. Persist candidate parameters in existing result artifacts; only a verified server receipt activates them for the next round. Keep learned predictions separate from baseline counts and recover both from original artifacts. A label from the target race cannot appear in its training IDs.

Remove anticipatory HH:22 shutdown. Extend one existing session to 65 minutes / 24 rounds, retaining 240 total source requests and 45 per round / 210-second cutoff buffer. Same concurrency group and at most one queued successor through the existing hourly automation. No claim of hard-real-time delivery or zero missed races. Record each ended scheduled race's five-model coverage and missing IDs.

## Tasks
- [x] Add failing tests for no early shutdown, audit coverage and learned-version safety.
- [x] Implement same-family training, immutable artifacts, source/time verification, candidate inference and paired scoring.
- [x] Wire the existing restore/forecast/audit/checkpoint pipeline and recovery. Keep ready baselines working on insufficient learning data.
- [x] Extend existing repeat-session bounds without increasing source budget; include missing-model coverage.
- [x] Run focused tests and original-input replay. Local 112 tests pass; 42 real P0 races independently replayed for a local fitting check.
- [ ] Execute existing workflow, verify a genuine fitted artifact and subsequent pre-cutoff shadow forecast; report measured boundaries.

## Review focus
No validation-result influence on fitted weights; no training after prediction timestamp; no synthetic training disguised as real; no loss of earlier rows during recovery; no modified historical picks, silent duplicate counting, or promotion of receipt-unverified research.

## Owner-confirmed continuation: all-race exact-eight target (2026-11-05)

Owner explicitly fixed the goal at all races, trifecta, exactly eight distinct ordered tickets,98% observed hit rate. This is a target, not a promised probability or a production promotion. Existing instruction to proceed to completion applies; no repeated design permission round, new external development task, model family, PR, workflow, paid service or real wager.

Design: reuse authenticated saved result journals to supply the existing two observed families with genuinely available recent finish/ST features. Existing coefficients and ranking equations remain unchanged; no-context legacy outputs remain byte-identical. Current raw results contain no verified actual course, so course features stay explicitly missing. An optional artifact-backed history context carries independently read parent receipt, actual verification time and immutable observations; per-race evidence selects only earlier races available before generation, excludes the target, deduplicates revisions, and identifies sparse captured-history coverage. The existing reader gets an explicit optional history path, preserving the original two-HTML-source path. Recovery independently matches included history observations to authenticated parent artifact proofs; a claimed digest alone never proves membership.

Interfaces:
- `race_ai/observed_result_history.py`: `context_from_result_archive(raw, receipt, *, verified_at)` -> sealed context; `history_proof(context)` -> receipt identity + observed member digests; `prepare_history(context, *, race_id, participants, as_of)` -> artifact source + per-registration features/missing + compact immutable evidence; `verify_history_evidence(evidence, *, race_id, participants, as_of)` -> same prepared output; `validate_history_proofs(evidence, proofs)` -> fail closed on parent/membership mismatch. Participants have `registration_no` and `lane`. Caller authenticates archive bytes; constructor also validates via existing result_archive. Fields for recent numeric mean finish/ST use existing transform/sample/history contract. Course means stay NO_VERIFIED_COURSE.
- `observed_p1_connection.build_bundle(..., history_context=None)` adds history only when explicitly provided; verified_rows validates new evidence deterministically, old bytes/readers unchanged. Existing source URL for history is the real GitHub artifact ZIP endpoint with ZIP digest; its captured_at is the actual independent verification time. Original result URLs/SHAs/times remain in evidence. No fabricated upstream URL or result-course mapping.
- `scripts/github_existing_cycle.py` and `cycle_recovery.py`: retain latest independently read history context/proofs separately from fitted learning context; pass context to the existing pilot; preserve all old originals and source-control latches. Parent proofs are rebuilt from authenticated result ZIPs during recovery. No extra official GET.
- Existing all-race evaluation: extend existing coverage audit with optional official observations and model-wise exact-eight target scores; conditional saved-only rates remain separately labeled. Missing forecasts contribute zero to all-normal-final-race hit coverage while keeping an explicit missing status, unknown/refund/abnormal results stay separate. Reuse existing scoring and Wilson helper; never count the five-model ticket union as eight or report a single-race98% probability. Same-family learned variants use explicit separate model/variant columns.

Review focus: future/cross-race history leakage; revised results counted twice; target-race self inclusion; F/L/dispositions or lane mistaken for actual course; forged parent metadata/history membership; source rights/time mismatches; silent rewrite of old Top8; missing predictions hidden from denominator; model-union inflation; point estimate98% presented as proof.

- [x] Write RED regressions for history chronology, revision/registration/disposition safety and legacy byte parity; implement and run focused GREEN.
- [x] Wire authenticated history through existing restore/forecast/complete/pilot path, with independently verified parent membership and preserved old originals; test recovery/old artifacts.
- [x] Write RED all-race denominator/exact-eight regressions, extend existing audit and report honest target status/uncertainty; run GREEN and actual saved-data assessment.
- [x] Run relevant full tests, independent review, source/input/output parity and private real-history dry run. Do not fabricate retrospective forecast performance or replay old original outputs as new forecasts.
- [x] Recheck public HEAD/writers/cancelled checkpoint, apply only reviewed changes to existing PR; record achieved/untested/blocked conditions in RACE_AI_LATEST_STATUS. No cancellation bypass or production promotion;98% remains unachieved until sufficient future results support it.

## Owner-requested additional BOAT observations (2026-11-05)

Continue the existing PR and collector. Parse official beforeinfo even while exhibition is pending; retain weight, adjustment, tilt, parts, weather, exhibition ST and source identity. Read official pit reports as attributed source comments, distinguishing an unoffered report from an unsupported layout or fetch failure. Retain private originals outside Git. A separate optional display context must never rewrite saved picks or claim the old model used newly collected facts.

Use official historical B closing/roster and K actual entry/results, joined by exact day/venue/race/registration. Report inward entry, outward displacement and crossing by outer-frame boats as conditional sample counts and finish rates; these observations do not prove intent, resistance or causality. Keep unknown turn style, exit acceleration, run-up and straight extension explicit; a venue-level video link is not a reviewed race clip or a speed measurement. Reuse existing reviewed video evidence contracts when evidence becomes available.

Files/interfaces: `boat_observation_context.parse_beforeinfo/parse_pitreport(raw, *, source_url, captured_at, expected_race_id, roster)`; `boat_entry_observations` verified daily B/K bridge and conditional profiles; private `boat_context_store` sidecar, existing pilot collection hook, and preview-tab display. No new inference family or dependency. Existing cancellation review latch remains in force; collection inspection does not restart the cancelled forecast workflow.

- [x] RED/GREEN parser tests: empty exhibition, source/roster mismatch, actual comments/unoffered reports, capture eligibility, unknown visual metrics.
- [x] RED/GREEN historical join tests: actual closing, dates/rosters/source hashes, as-of availability, crossing without course displacement, empty denominators.
- [x] RED/GREEN integration tests: preserve ready forecasts on optional-context failure; same source wait guard, private append-only originals, read-only sidecar and unchanged saved forecasts.
- [x] Parse real private captures, retain source SHA/time evidence, show facts and gaps in mobile/desktop browser; run full checks and independent review.
- [x] Record implemented, measured and still unavailable items in latest status; apply reviewed source changes to existing PR only.
