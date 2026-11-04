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
