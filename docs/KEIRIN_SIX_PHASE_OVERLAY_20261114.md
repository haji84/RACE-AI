# KEIRIN existing PR71 + video: six-stage scoring integration (2026-11-14 JST)

## What this draft implements, and what it does NOT

This change adds a **research scoring overlay**, not another forecasting engine, video recorder, video classifier, learning loop, or settlement authority. It is stacked on Draft PR #290, which repaired prior-history acquisition fairness and clarified the zero-video archival HOLD.

Existing assets retained:
- Four-model PR71 original and Git AES storage: `race_ai/keirin_pr71_four_model_rank.py` on immutable source `fe7e558...`; main `scripts/keirin_cloud_pr71_state.py`; `race_ai/live_15min_proof.py` for the prospective 10–15 minute acceptance gate.
- Video collection, clip admission and scene research: existing PR #102 (`race_ai/keirin_video_clip_policy.py`, `race_ai/keirin_video_events.py`, `race_ai/keirin_video_postrace_pdca.py`, source ref `c26ac092...` pinned by main).
- Research variable-selection and full-ranking work: existing PR #103, not independently replaced.
- Existing site and PDCA remain unmodified.

New file: `race_ai/keirin_phase_overlay.py`. The paired source-free tests are `tests/test_keirin_phase_overlay.py`. Existing KEIRIN PR71 synthetic CI runs those tests on PR branches; main-only forecast actions remain unchanged.

## Strict chronology

1. **Before cutoff**, receive six structured phase hypotheses from the existing PR71-related inference process, with one of its four model IDs and its **actual saved parent prediction SHA** and input SHA. The present production models do **not** independently produce authenticated six-phase tactical forecasts. This is an unconnected interface, not a claim that they already do.
2. `build_phase_forecast` checks aware runner clock, earlier parent save and at least 65 seconds until official sales cutoff; `freeze_private_once` creates a file only once (no overwrite or symlink), then independently byte-reads and SHA-checks it. This is a private sidecar, not an uploaded new formal original. Later production wiring must put it in the **existing** encrypted Git state and prove independent separate-runner readback.
3. **After cutoff**, the existing PR #102 clip reviewer supplies `RACE_AI_KEIRIN_CLIP_TRAINING_ADMISSION_V1`, exact recording SHA, independently reviewed frame hashes and review references. An independent visual analyzer/reviewer must give per-stage timing, rider order, line state and attack action; it cannot mark all six stages merely from a 2–3 minute video length. A high-level scene classifier alone is not rider tracking.
4. The overlay checks the admission SHA, same race ID, complete frame hash/review reference pairing, time proximity, correct phase order, and no duplicate phase frames or live observations backed by replay frames. The calling owner host must independently attest frame correctness and rights; metadata booleans are **not** proof.
5. Separately authenticated official results may validate GOAL order and reject a conflicting visually observed top three. They never enter the before-cutoff prediction or rewrite it.
6. Return a digest-bound, private **post-race research comparison**. A formal input-attested comparison additionally requires independent frozen PR71 original, the existing prospective-window proof, video frames and rights, and the official result. Even then **learning is not performed, official ROI is not updated, and weights are not promoted**.

## Fixed, preliminary 100-point rubric

| Phase | Max points |
| --- | ---: |
| INITIAL / 初周 | 10 |
| BELL / 打鐘 | 15 |
| FINAL_HOME / 最終H | 15 |
| FINAL_BACK / 最終B | 20 |
| FOURTH_CORNER / 4コーナー | 15 |
| GOAL / ゴール | 25 |
| **Total** | **100** |

Within each phase, the initial component shares are leader 25%, ordered top three 35% (each position one-third), line groups 15%, second wheel 15%, and independently visible attack/outcome 10%. These component shares are **untrained research choices**, not a calibrated improvement claim.

A value not observed, not forecast, not independently verified or outside a live frame is `UNKNOWN`. Report separately:
- `visual_observation_coverage_pct`: observed/attested video-component weight out of 100.
- `comparison_coverage_pct`: both predicted and observed component weight out of 100.
- `earned_points_out_of_100_possible`: raw weighted points earned.
- `accuracy_on_comparable_components_pct`: earned / comparable weight; `null` if none.

For example, a perfect result on only the 20-point final-B phase is **20/100 raw, 20% coverage, 100% accuracy on comparable components**. It must never display an unqualified 100-point overall score. The phase statuses and missed *component categories* support later root-cause analysis, but without a controlled evaluation they do not establish why a rider moved or whether the new model predicts better.

## 武雄2R (Takeo 2R) test classification

User-reported information: a ~2m48s screen recording, chat-only forecast, and a reported top three 1-7-2. This message does **not** supply an authenticated race ID/date, video byte SHA, pre-cutoff GitHub model original SHA, independent receipt or verified official result. No such original or footage was found as an attachment usable in this development run. Therefore:
- Case is reserved as **RESEARCH_ONLY_NOT_FORMAL**; do not reconstruct the chat forecast as a retroactive pre-cutoff original.
- No real independent rider/line/attack annotations have been generated here. Specific claims (1 succeeded leading; 4 lost position; 7 and 2 advanced) stay **hypotheses for later video review**, not automated label ground truth.
- The supplied result 1-7-2 is **user-reported**, not an authenticated official result in this code change. Do not put Takeo 2R into formal win rate, payout totals, or training.
- If the actual clip is available to a permitted private analyzer, inspect precise frames and label only visible stages; all others remain UNKNOWN.

## Live acceptance blockers verified 2026-11-14

- Actual owner forecast cycle `43582550517` was green at the workflow level yet real source acquisition stopped after an access denial. The run is not proof of a new formal model freeze.
- Capture `43567244002` found 67 races, 24 completed replay links, captured + AES-sealed **8** browser clips, generated 362 scene-feature frames, and **0** independently verified rider-tactics labels. Video archive step failed because private durable storage was not configured. Independent video acceptance `43568226669` returned `SOURCE_ARCHIVE_NOT_ATTESTED`.
- Clip artifacts have temporary GitHub retention. No new external storage or owner computer archival is authorized or deployed by this draft.
- GitHub Actions schedule delivery can be delayed or skipped; CI green is only code-path evidence.

## Remaining work before calling the full pipeline finished

1. Repair owner-approved source availability/rights and missing 93-slot input facts without bypassing provider denial. Produce the first real four-model pre-cutoff frozen original and independent readback.
2. Attach the six-phase projection callback and its private immutable sidecar to the *existing* owner source + AES archive, ensuring independent release SHA/receipt and no post-race backfill.
3. Reuse existing PR #102 frame/clip admission but extend its actual rider identification, line and stage labeler; validate blinded against independently reviewed annotations on accessible permitted clips. UNKNOWN must not turn into a false zero/negative.
4. Connect existing archived ciphertext + authenticated official result by exact race ID, exact SHA and event ordering. Retry provider transient failure only when permitted; deduplicate clipped scenes and result revisions.
5. Add an authenticated **read-only** site view for per-stage score/coverage and error category; no raw video or private original exposure in public Pages.
6. Evaluate many future *unseen* race cohorts, compare the unchanged four-model baseline vs any candidate, and promote weights only after robust independent evidence and owner approval.

**Acceptance is separated**: code and synthetic CI; actual video/forecast production; genuine post-race comparison; and independently proven out-of-sample improvement. They may not be collapsed into one green check.

## Additional code-path integration evidence (GitHub CI)

- `build_from_existing_pr71_saved` consumes a **verified existing** `FourModelRankLedger.read_suite(race_id)` row, checks matching race/cutoff/as-of, and binds the exact saved per-model `prediction_sha256` and `snapshot_sha256` to the separate six-phase sidecar. It requires a trusted independent source-suite verifier and does **not** manufacture stage forecasts from Top8 combinations.
- Existing SHA-pinned PR #102 `keirin_video_clip_policy.assess_clip` runs in a source-free, fictional clip integration test; only independently reviewed frame IDs admitted by that existing policy can enter the stage overlay. This is not a new video learning/classifier engine.
- GitHub Actions [43586082434](https://github.com/haji84/RACE-AI/actions/runs/43586082434) on research PR #291: completed SUCCESS. New research checks: phase overlay **23**, existing PR #102 clip admission integration **2**, existing PR71 frozen SQLite model integration **4**, totaling **29** source-free tests. Other existing CI regressions also passed. Test rights/clock callbacks in these fixtures are simulated and are **not** real independent receipts.
- The freeze rejects a directory accessible to other users, reducing risk of saving unencrypted stage forecasts in the public repository workspace. It still requires a correctly configured owner-private AES Git archive for durable retention; no such production sidecar archive has been deployed.

### Outstanding connection and activation boundaries

The PR71 read-suite adapter and video admission adapter now pass **code-path integration** with synthetic evidence. Neither has been called with a live, independently authenticated pre-cutoff race plus permitted actual rider-recognized video. Actual future stage projection, Git AES private sidecar persistence, independent race footage labeling, automatic join and PDCA scoring, read-only Pages display, and blind out-of-sample model improvement are still separate, UNVERIFIED production gates.


## 2026-11-15 JST: actual 403 root cause, source safety repair and frame-ID validation

### Production evidence, not synthetic completion

- [main PR71 run 43615418955](https://github.com/haji84/RACE-AI/actions/runs/43615418955) reached a source-owner HOLD after one provider request for 2026-11-15 JST: provider_denial_stopped_requests=true; new_pre_race_inputs=0; actual_four_model_forecast_saved=false; independent model readback skipped.
- The [video capture fallback run 43619018351](https://github.com/haji84/RACE-AI/actions/runs/43619018351) uploaded 14-day **metadata-only** artifact ID 14123028109. The exact downloaded ZIP SHA256 is 9a62bda0fd0df47ee7822c5c5c84fa52e32d168b89e8112d6bc42c1a832cf09a; internal keirin-daily-wave.json SHA256 is 85028784427923331d0a875a7786b6461f6300c980760aeaff79084ab9744c91. Authenticated workflow metadata reports 67 indexed races, 24 result links, 24 attempts, 24 HTTP 403, zero encrypted clips and zero independently verified tactics. All 24 had been marked INCOMPLETE_NOT_EXPORTED with failure_type=RACE_IDENTITY_MISMATCH, wrongly conflating a source refusal with a genuine mismatch.
- Do not bypass/retry HTTP 403 or 429, switch hosts silently, or conclude the race URL format is defective without a successful source page.

### Existing Draft PR #102: bounded source-denial repair

- scripts/keirin_winticket_historical_batch_capture.py now distinguishes HTTP 403/429 SOURCE_ACCESS_DENIED_NO_RETRY from actual HTTP-200 race/title mismatches. Denied responses never read the title, attempt player playback, or claim ciphertext video.
- scripts/keirin_daily_dynamic_clip_collector.py stops the SAME wave after the first 403/429, deferring the remaining candidates and preserving public-safe hold fields: provider_denial_stopped_wave, provider_denial_http_status, provider_denial_deferred_in_wave. No new scraper, rights, alternative host, or source retries.
- All **5 source-free regressions** passed on [Actions 43621134941](https://github.com/haji84/RACE-AI/actions/runs/43621134941). That CI is not a production video capture.
- Existing video source for the two PR #291 research/CI checkouts is pinned to exact verified PR #102 HEAD c52ff0216435b97a0209c43bbe5d0de589445736. Existing main, provider permissions, model weights and past encrypted originals remain unchanged.
- scripts/keirin_cloud_owner_inputs.py adds source_capture_hold_code and source_session_stop_code for denial, deadline, unpublished and network/unavailable, exposing neither source HTML, rider identity nor arbitrary exceptions.

### Existing PR71 + PR102 frame-to-rider bridge on Draft PR #291

- race_ai/keirin_frame_rider_identity_gate.py accepts CANDIDATE car numbers, normalized boxes and position observations from source-bound PR102 reviewed video frames, not from official final results or model predictions. It verifies exact admission/frame SHA pairs, review refs, frame times, distinct LIVE frames, unique roster riders, position ranks and confidence before producing limited phase observations.
- Two separate frames must agree on a car number and race position. A signed, independently restored existing PR71 roster/model snapshot and separate visual/pixel attestor are required. Missing, conflicted, low-confidence, duplicate/replayed or source-mismatched frames yield UNKNOWN.
- bridge_from_existing_pr71_ledger binds riders to actual PR71 read_suite source starters, model ID, parent prediction SHA and input SHA rather than an arbitrary manually typed field.
- Only observed leader and ranked top three feed the existing six-phase scorer. Line groups, actual second-wheel, attack type/success, and all unseen phases remain UNKNOWN. Camera geometry alone is NOT a race rank; a two-frame metadata vote is not proof of real OCR recognition.
- The new source-free regressions cover absent rights/pixel review, low confidence, changing ranks, video-replay frames, missing hashes, incorrect roster, duplicate car/rank, and mismatched saved model SHAs. No new forecasting model or independent video AI was created.

### Remaining live acceptance gates

1. Legitimate source access and complete before-cutoff inputs; real PR71 4-model frozen AES original with separate-runner readback. Source refusal remains a HOLD, not a success or a prompt to evade restrictions.
2. Authorized real video pixels in a private GitHub Actions runtime, actual numeric OCR/visual rider detection from frames, reviewer-labeled ground truth, and measured identity precision/coverage. This continuation has **zero** such real verified rider-number cases. A private RSA key and permitted footage have not been supplied to this analysis.
3. Independent frame-level line continuity/second-wheel/attack recognition, race-ID alignment, authenticated official result and stage scores; each unknown component remains excluded.
4. Resume/retention without public raw video and without requiring owner ZBook storage. GitHub artifacts expire; permanent private storage remains unconfigured and no new paid service is authorized.
5. Read-only safe site display, paired future-race A/B holdout assessment, and owner-approved model promotion only after independent evidence.

Implementation/CI acceptance is distinct from actual real-race video recognition and model improvement. **Main production acceptance remains NOT PROVEN**.
