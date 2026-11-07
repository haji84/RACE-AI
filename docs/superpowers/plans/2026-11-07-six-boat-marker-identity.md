# Six Boat Marker Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task.

**Current goal (owner steering, 2026-11-07):** Identify the six riders primarily by clothing colours (white/black/red/blue/yellow/green), without requiring a readable printed digit, and retain identity using measured current pixel tracks. Historical printed-marker experiments below remain preserved.

**Architecture:** Separate automatic printed-number discovery/recognition from marker association. Keep the existing detector-first provider and camera/strength path compatible.

**Tech Stack:** Python/OpenCV, optional pinned full37 CRNN/full6625 PP-OCR, declared development HOG/SVM, private original footage and existing local FFmpeg.

**Spec:** `docs/superpowers/specs/2026-11-07-six-boat-marker-identity-design.md`.

## Global Constraints

- Existing PR71 only, no new forecast family/workflow/task/service/fee, no public/main/wager/production-model change.
- No denied source retries or alternate host/IP/UA/token workarounds. Existing autoplay and prediction PIDs remain running.
- No acquisition-count/runtime ceilings. Analysis resource conditions remain explicit, not hidden candidate success.
- No injected GT ROI/number or repeated stills as temporal evidence. The owner's latest explicit instruction authorizes canonical clothing-colour identity; colour candidates remain separately typed from printed-number evidence and require actual current pixel lineage.
- Preserve originals/references/weights; model eligibility and field validation remain false until genuinely established.

## Review Focus

Repeated views counting as fresh frames; numeric fragments of equipment labels; overlapping but distinct printed marks; OCR gaps vs invisible marks; camera cuts/time discontinuities transferring stale identity.

### Task 1: Image marker association

Create `race_ai/boat_video_marker_identity.py` and `tests/test_boat_video_marker_identity.py`.

Interface is the `MarkerIdentityTracker.update` contract in the spec. Use unambiguous one-to-one geometric correspondence and explicit conflicting/duplicate rejection. Unit tests use injected numeric observations only as controlled algorithm inputs, never real-field acceptance.

- [x] RED: Six separate markers require three distinct frame observations; repeated/duplicate views do not satisfy this.
- [x] RED: A visible marker with temporarily empty OCR can retain an already anchored ID, but missing marker, .5-second age/gap, cut, size change and conflicting/multidigit observations cannot inherit it.
- [x] Implement minimal marker tracker and GREEN all corresponding cases, including crossing/ambiguous neighbors and atomic invalid-input rejection.
- [x] Independent task review, including separately typed non-probabilistic classifier evidence.

### Task 2: Automatic original-pixel marker reader

Create `race_ai/boat_video_marker_reader.py` and corresponding tests after the frozen all-candidate native experiment establishes viable localization/recognition. No truth-selected crop enters the product reader.

- [x] Freeze complete automatic candidate experiment, raw outputs and separate scoring.
- [x] RED for the proven localization/processing/context failures, then implement fixed full-frame localization and pinned full37 native recognition.
- [x] Validate complete/unknown/multidigit envelopes and real-pixel source/provenance.
- [x] Independent reader review and measured performance; actual PP-OCR output equivalence and both development classifier outputs each checked on all3060 candidates.

### Task 3: Local sequential execution and actual six-class acceptance

Connect the reader/tracker through a local-only sequential executor and existing intake compatibility as warranted by actual inputs. Do not change production defaults.

- [x] Run actual frames without GT ROI through the full automatic path; seal output before scoring (76 source frames; training overlap explicitly retained).
- [x] Score the six independently sealed local tracklets, including intermediate continuity/swap checks, negatives, scene cut and unavailable evidence (all six remain below the continuity criterion).
- [ ] Fix observed failures rather than lowering the required numeric evidence.
- [ ] Run relevant and full repository checks; preserve latest concurrent HEAD without force.
- [ ] Update latest status with implemented/actual-pass/unmet/external-source conditions and exact evidence, never call a static-only or zero-ID result complete.

## Continuation: diagnose the actual missing observations before further changes

The user renewed the request to finish automatic identification. Reusing a
failed model or relaxing the duplicate/minimum-evidence rules is not a fix.
The final 76-frame output can be replayed through the same pinned marker
association code: all 76 identity records reproduce exactly. In the fixed 102
reference opportunities there are 59 registrations and 43 missing results.
Of those missing results, 31 already have a current numeric marker reaching
association: ten association restarts and 21 results below three observations.
The latter include normal first-seen warm-up, so they are not all software bugs.

Five of the ten restarts have the **same actual LK context key, TRACKED status,
and same fresh number** as the preceding observation: 2 at frames 207/211/215,
1 at 241, and 3 at 316. The marker association module discards that pixel
correspondence and estimates correspondence again from box velocity/area.
Three of these restarts discard an already established three-frame identity.
The narrow correction is to carry typed current-pixel correspondence into
association, preserving all numeric, duplicate, conflict, scene and time rules.
It must not apply to a newly SEEDED key, blank-number transfer or hidden boxes.
LK context continuity is explicitly not proof of hull identity.

The duplicate-number failures at frames 480/482 have a different cause: both
the actual marker and an orange/black bank fender pass the development context
and glyph classifiers as 4. The duplicate guard correctly abstains. Changing
that guard would hide the false positive. The context's small glyph patch is
not a hull detector; background rejection needs a separately tested correction.

- [x] Reproduce missing-stage causes from frozen actual output, separating
  measured cases, controlled-only hypotheses and unavailable annotations.
- [x] RED/GREEN the five same-pixel-lineage restarts with explicit, atomic
  correspondence and adversarial checks; independently review the change.
- [x] Re-run actual automatic inference without truth-selected input crops;
  score changed and unchanged events before any acceptance claim.
- [ ] Resolve background false positives while preserving genuine markers;
  use only assets with training permission and disclose development overlap.
- [ ] Establish a distinct visible-object/number-binding contract and test
  actual simultaneous six-boat continuity, lost/reacquired states and cuts.

## Continuation: distinct visible-rider and print evidence

- [x] Decode the existing pinned COCO PERSON head separately; preserve boat defaults and source pixels.
- [x] Verify all18 anchor PERSON parts, then actual61 original frames/427 forwards and all373 native candidate rows.
- [x] Implement anonymous current-pixel rider lifecycle with typed optional physical-print pairs and no default number producer.
- [x] RED/GREEN replay conflicts, shared/near-shared print claims and overlapping flow-only parts; independent review.
- [x] Replay actual detections with actual LK on61 native frames, seal before semantic scoring; retain false motors/duplicates.
- [x] Add optional existing CLI rider output, local assets only, separate numbers and fail/partial preservation;670 relevant tests PASS.
- [x] Resolve demonstrated rider association resets using current points, without reducing numeric or ambiguity requirements (six primary anonymousR keys continuous on61/2s; motor25/numbersUNKNOWN retained).
- [ ] Complete automatic physical part/print binding and actual simultaneous six numbered identities, with extras/misses/swaps audited.
- [ ] Add already-licensed local direct-print diversity; evaluate a suitable image representation with no unknown-rights training.

In the previous7d trace, all17 retired keys still had current LK support; no LK loss was reported across those61 frames; output scope remains image hypotheses. All source-only truth joins are post-inference diagnostics. UNKNOWN/Todo is private inference only. Number/CNN capacity, semantic gate and body tracking are distinct tests; no failed prototype is promoted to forecasting.

- [x] Audit current-point actual61 outputs and all373 raw observations;362fresh+11UNBOUND,391output rows,6same-primaryR across61; retain motor25.
- [x] Verify exact6/nonzeroPTS fixture, then retain the concurrent upstream MP4 muxer-offset/packet-count correction; first677 local tests PASS, mergedCLI16PASS and merged677/68.198s PASS; no latest full-CI green assertion.
- [x] Add licensed36 photo glyphs to the distinct glyph-CNN training dataset; oracle18 capacity8agree/9reject/1wrong remains unmet.
- [x] Prepare9 licensed source-visible rider examples for the separate RGB appearance dataset; preserve3 excluded/UNKNOWN and do not mix them into the glyph-CNN experiment.
- [ ] Finish clean RGB person/appearance training and automatic-proposal validation, including motorfalse/unknown/sourcegroup restrictions.
- [ ] Establish hull pixel-instance/physical-binding evidence without truth prompts; test all masks and extras, never certify a generic proposal as wholecraft.


## Owner-directed clothing-colour continuation

- [x] Primary clothing-colour candidates independent of printed digits; pale-green/neutral ambiguity, mixed and duplicate handling.
- [x] Real current-pixel lifecycle and separately typed current colour vs held prior evidence; repeated frames do not add votes.
- [x] Private snapshot/source hash and atomic final allocation regression, independently RED/GREEN reviewed.
- [x] Existing CLI clothing-only execution without OCR assets, all-frame private journal and receipt.
- [x] Native61 actual LK/cached actual detections, then fresh pinned427 forwards from lossless BGR-equivalent video;57 continuous all-six mapping agreements,0 wrong/motor labels.
- [x] Related696 video tests PASS, preserve earlier failures and concurrent branch updates.
- [ ] Semantic garment isolation, mixed black/coloured hood diversity, crossing/occlusion and separate venues/long recordings.
- [ ] Current LIVE availability, real-time throughput and validated hull/strength/forward forecast improvement.

The61-frame result is an already-known low-motion development sequence, not an independent holdout. Only13frames newly observe all6colours at once;57 continuous identities include real-pixel retention. Do not call the whole six-boat product field-validated.

## Owner-directed exhibition order and commentary cues

**Design:** Keep clothing/current pixels primary; supplement with declared individual-exhibition pass order and timestamped Japanese commentary. Exhibition order is a prior for individual passes, never simultaneous start-exhibition course order. Missing/duplicate passes, cuts, absent boats and unknown phase cannot silently advance an identity counter. Commentary running rank and boat number are separate fields; image x-order is never a running rank. Unbound/partial/corrected/old/finish utterances stay explicit. These observations never become official results or pre-cutoff prediction features.

**Files:** Fix embedded-audio preservation in `race_ai/boat_video_capture.py` with actual audiovisual roundtrip tests; add focused `boat_video_broadcast_context.py` plus parser/timing/crosscheck tests; connect optional local source-bound context to existing `boat_video_marker_analyze.py` and its tests. Local speech recognition is optional and requires pinned existing local assets; public sources are never fetched by the product parser.

- [x] RED/GREEN first embedded audio packet/PTS preservation, silent input, legacy receipt reuse and unsupported codec failure; no extra source GET.
- [x] RED/GREEN explicit rank/boat parsing, partial/duplicate/correction handling, exhibition prior versus phase/course and absent boats.
- [x] RED/GREEN exact mediaSHA/sourcePTS/availability/expiry validation, current cloth crosscheck, ambiguity and no future-result transfer.
- [x] Add existing CLI local context input and optional pinned local speech path; preserve originals and private receipts.
- [x] Run actual saved-audio transcription if possible, seal raw output before parsing; no speech/identity accuracy claim from a transport smoke test.
- [x] Independent review, related regressions, preserve concurrent PR71 updates and latest status.
