# KEIRIN existing-asset repair and Takeo 2R research handoff (2026-11-14 JST)

## Goal and non-goals

Finish the **existing** RACE-AI KEIRIN source collection, pinned PR71 four-model prediction, AES-GCM Git history, encrypted video capture, and post-result PDCA. Add phase-by-phase (initial lap / red board / bell / final home / final back / fourth corner / goal) video scoring only **after** those assets have reliable inputs and separately verified real production outcomes.

Do not add a second video AI, model authority, betting integration, provider-scraping grant, service, scheduled task, Cloudflare, Vercel, runner, or paid storage. Keep public GitHub free of raw footage, identifiable private research, prediction originals, secret keys, and unredacted source bytes. No change to frozen prediction originals, model weights, or active production branch in this draft PR.

## Verified current source of truth

- Repository: https://github.com/haji84/RACE-AI ; examined main `b4206312594ef84a43c86695dc3d3ec16d1c5ae0`.
- Main PR71 run https://github.com/haji84/RACE-AI/actions/runs/43540818026 , launched 2026-11-14 10:28 JST: workflow **success**, but owner cycle reports `HOLD_OWNER_SOURCE_PARTIAL_NO_COMPLETE_PR71_INPUT`, `new_forecasts=0`, 67 indexed races, 6 eligible linked racecards, 3 prior-history checks, 3 deferred, 252 source GETs and monotonic work-budget exhausted. Independently verified model-readback job **skipped**. It did not produce a formal result or official PDCA score.
- Public preflight in the same run: one selected 7-rider race had 74 of 347 observed checks; **79 required A model-input slots absent**; 57 critical preflight source slots missing. This count is not a statement that every live race has identical gaps.
- Video capture run https://github.com/haji84/RACE-AI/actions/runs/43515565309 : 67 indexed races, 0 finished result links, 0 attempted recordings, 0 encrypted clips; the archival shell step also failed because the optional/private durable archive bucket was not configured. Those are **two separate states**: no video available yet versus no durable object-store configuration.
- Later scheduled *nightly research* workflow https://github.com/haji84/RACE-AI/actions/runs/43534569132 was green, but capture job was skipped and owner-private RSA key was unavailable; it was **not** evidence of a successful video capture.
- Independent storage acceptance https://github.com/haji84/RACE-AI/actions/runs/43534665518 returned `SOURCE_ARCHIVE_NOT_ATTESTED`. No private durable PUT/GET/SHA has been established by this run.

## Narrow repairs implemented on this research branch

1. Existing source collector `scripts/keirin_cloud_owner_inputs.py`: divide a maximum **120 candidate historical-result page attempts** fairly over currently prospective races, with a per-race ceiling of 32, rather than asking each candidate for up to 100 before later races are inspected. Other page classes (racecard, odds, discovery) are **not** part of the 120; the same 240-second budget, no provider-denial retry, custody restrictions, cutoff, missing-input HOLD, and original model output remain unchanged. This is a performance/coverage opportunity, **not** a guarantee of full 93-slot completeness or official forecast creation.
2. Existing GitHub video workflow `.github/workflows/keirin-github-autonomous.yml`: validate the actual encrypted-clip count first; with 0 clips mark `HOLD_NO_ENCRYPTED_VIDEO_TO_ARCHIVE` and skip an S3 upload attempt. If any real encrypted clips exist, unconfigured S3 still returns `DURABLE_PRIVATE_STORAGE_NOT_CONFIGURED` with nonzero exit. No empty-clip branch can mark independent durable storage success. The separate consumer continues to require real upload evidence and byte SHA.
3. Source-free test additions: ensure six prospective racecards get shared 20-page candidate caps and no partial model promotion; one race retains max 32; ensure video zero-clip HOLD precedes missing-bucket branch while real clips still fail without archive. These are offline regressions, not success with real recordings.

## Takeo 2R: first phase-scoring research case, not a formal outcome

- Reference is the user-mentioned "今回の武雄2R"; **race date, official race ID, video bytes/SHA, saved model prediction SHA and verified cutoff receipt are not established in this handoff**. Do not invent them.
- The prediction discussed in a chat is **not** independently verified as a GitHub pre-cutoff frozen formal original. Its outcome cannot enter production model training, official hit-rate, recovery rate, or ROI.
- Reuse Draft PR #102's existing `keirin_video_events.audit`, `keirin_video_inference`, `keirin_video_postrace_pdca`, `keirin_video_tactics_pr71_ab_gate` and PR #103's existing forecast-ranking/PDCA components. Do not create a separate video model. In current PR #102, `keirin_video_events` and `keirin_video_lap_gate` contain Matsuyama-specific admission rules; a Takeo research input must explicitly address those scope constraints **before** attempting to call a four-lap real-evidence gate.
- Proposed seven-stage **research-only** rubric, for each stage: observed recording timestamp/frame digest; verified rider identity/line shape if visible; predicted vs observed position/attack type if an independently saved pre-race hypothesis exists; `MATCH`, `MISS` or `UNKNOWN` with reason. An unobserved stage is `UNKNOWN`, never an implicit wrong prediction or negative example. A short digest does not prove that all laps or stages were captured; replay segments must not be counted twice.
- Only verified post-cutoff official outcome records may be used for **retrospective** research scoring. A formal comparative A/B statistic additionally requires actual frozen GitHub forecast originals timestamped before the real cutoff, independent ciphertext readback, official result authentication, and out-of-sample evaluation. Keep later-stage actual movements out of earlier pre-cutoff feature input.

## Acceptance gates (two separate verdicts)

| Gate | Implementation/CI | Live production |
| --- | --- | --- |
| Fair historical-page candidate budgeting | Code + source-free regression proposed in this draft | Needs later main scheduled or trusted fallback run with public-safe count proof |
| No-video vs S3-missing categorization | Workflow + source-free wiring regression proposed in this draft | Needs real capture-wave report and independent archival classification |
| Reliable full PR71 input and immutable four-model forecast | Existing pipeline; this PR does **not** change the model/data permission gate | **HOLD**, 0 formal models saved in checked run |
| Private encrypted video retention | Existing temporary sealed artifacts and independent verifier | **NOT VERIFIED** durable archive; no new store is authorized here |
| Takeo 2R phase scoring | Research-case policy only; no evidence-bearing score invented | **NOT RUN / NOT FORMAL** |
| Stage-conditioned improvement to official 4-model predictions | No coefficients, model code, or PDCA authority changed | **NOT VERIFIED** |

A GitHub Actions green check means the tested code path completed; it never substitutes for an actual video, sealed byte SHA, frozen forecast, or official result. Maintain Draft/NO MERGE status until CI and then independently assessed production acceptance.
