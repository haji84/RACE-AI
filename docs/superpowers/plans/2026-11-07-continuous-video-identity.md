# Continuous Video Capture and Number Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement private continuous acquisition of authorized video and correct the proven automatic hull-number localization bug, then verify actual decoded footage.

**Architecture:** An independent HLS collector saves immutable segments/maps and durable request/wait state. Local-only exports feed a separate bridge to the existing intake; unverified race identity remains capture-only. The existing CRNN region selector receives only the causal positional-prior fix first.

**Tech Stack:** Python3.12 standard library, SQLite, urllib with inherited proxy/CA, local FFmpeg, existing OpenCV/YOLOX/NanoDet/CRNN.

**Spec:** `docs/superpowers/specs/2026-11-07-continuous-video-identity-design.md` and `docs/CODEX_RACE_AI_UI_PRODUCT_COMPLETION_20261104.md`, with latest user no-acquisition-cap instruction taking precedence over older numeric-limit text.

## Global Constraints

- Existing Draft PR71 only; no new issue/PR/workflow/schedule/paid service/forecast family.
- No main/public deploy/wagers/production model switch or protected runtime restart.
- No denied-footage retries or alternate-host/IP/UA/token bypass; existing HTTP wait policy remains.
- No total GET/segment/round/runtime ceilings; parser/resource/one-clip validation remains distinct.
- Keep original predictions/media/annotations/weights immutable and private; source claims are not independent authorization.
- No fabricated probabilities, current race identity, source timestamps, six-boat tracking or accuracy claims.

## Review Focus

- A signed URI/query or upstream error must not leak through summaries, state errors or CLI stderr.
- A crash around a GET must preserve unknown issuance, not reset real attempts to zero.
- Sliding/encoder-reset/discontinuous feeds must not produce a falsely continuous clip.
- A valid single digit above a hull's vertical center must remain detectable without admitting colors or multi-digit equipment labels as identities.
- A newly exported historical/test clip must not become a current pre-cutoff official source by template declaration.

### Task1: Durable authorized HLS collector

**Files:** Create `race_ai/boat_video_capture.py`; create `tests/test_boat_video_capture.py`.

**Interfaces:** `HTTPResult(status, headers, body)`; `Collector(root, manifest, fetch=None, clock=None).tick()` returns safe status/counts/wait/ready-window IDs; `Collector.export_window(window_id)` returns local MP4 path/SHA/capture receipt. Source manifest keys are pinned in the spec. Default finite analysis windows do not stop overall acquisition.

- [ ] Write RED tests for 37 arriving segments, restart deduplication, durable unknown attempts, corrupted saved bytes, missing segments, map/discontinuity boundaries, keys/unsupported features, byte ranges and origin/redirect guards.
- [ ] Run `python -m unittest tests.test_boat_video_capture -v`; confirm missing feature failures.
- [ ] Implement the collector with existing wait policy, private metadata and streaming atomic writes; implement local-only export.
- [ ] Run the capture tests and a local FFmpeg-generated fragment export; assert no network input reaches FFmpeg.

### Task2: CLI and existing-intake bridge

**Files:** Create `scripts/boat_video_capture.py`; create `race_ai/boat_video_capture_bridge.py`; create `tests/test_boat_video_capture_bridge.py` and `tests/test_boat_video_capture_cli.py`.

**Interfaces:** CLI reads a private source JSON and invokes Task1 in tick/follow/export modes. Bridge accepts a completed capture export and an existing JOB_V1 template, validates capture/media/time consistency and invokes existing `enqueue`; no template means capture-only. Historical/test data is never silently promoted to current official identity.

- [ ] Write RED tests for capture-only default, malformed/forged export rejection, before/after-cutoff clocks, roster/source consistency and safe stderr.
- [ ] Run the bridge/CLI tests to observe expected failures.
- [ ] Implement follow without total-count/time ceilings, respectful waits, graceful signal handling and explicit owner-declared intake binding.
- [ ] Run bridge/CLI tests; verify unchanged prediction originals and no foreground process/service side effects.

### Task3: Causal number-region fix

**Files:** Modify `race_ai/boat_video_crnn.py`; add `tests/test_boat_video_number_positions.py`; preserve existing CRNN tests.

**Interface:** Existing `candidate_regions(crop)` and reader/provider signatures remain compatible. No confidence/vocabulary/temporal changes.

- [ ] Write a RED translation-invariance test that loses the same upper hull glyph under the old positional rule, plus multi-digit/edge/bounds regression cases.
- [ ] Remove only the invalid lower-hull positional assumption; keep the other inference/UNKNOWN guards.
- [ ] Run the new and existing CRNN/identity tests and actual sealed six-photo diagnostic with fixed weights.
- [ ] Analyze actual sequential video with the existing physical/identity gates; record correct/unknown/failed results rather than claiming six-boat success from stills.

### Task4: Real transport and end-to-end verification

**Files:** Evidence summaries in `docs/evidence`; update `docs/RACE_AI_LATEST_STATUS.md` and usage documentation. Private real media/results remain outside Git.

- [ ] Use newly authorized CC continuous video and existing licensed Japanese video as clearly labelled historical/development inputs.
- [ ] Serve derived HLS on owner-only localhost; capture progressively through Task1, export via Task2 and verify source frame/PTS continuity. Do not repeat still images or call localhost an official LIVE.
- [ ] Run the full Python suite, relevant Node/CLI checks and independent source/identity review.
- [ ] Preserve concurrent HEAD changes by non-force integration; record exact HEAD/check results and remaining field-access/6-boat acceptance gates.
