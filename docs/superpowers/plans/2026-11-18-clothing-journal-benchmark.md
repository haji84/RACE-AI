# Clothing journal benchmark interface repair

> Implementation is local and offline. The owner requested continuation without repeated design questions; the parent worker approved this focused evaluation repair. No model, producer, workflow or publication changes are included.

**Goal:** Evaluate the existing clothing-only CLI output against explicitly typed rider-part references, preserving the existing hull benchmark.

**Architecture:** Add `benchmark_clothing_identity(journal, reference, *, configuration=None)` to the existing benchmark interface. A focused module consumes the original `RACE_AI_BOAT_MARKER_FRAME_JOURNAL_V1` rows and `pipeline_result.rider_part_tracking` without translating rider boxes into hull tracks. It reuses the existing geometry matcher and identity score arithmetic. No decoding, training, network access or forecast mutation occurs.

**Contract:** `RACE_AI_RIDER_PART_REFERENCE_V1` has the existing reference provenance/split fields plus `semantic_type=RIDER_PART_TYPED`; each reference frame contains `riders` with original-resolution boxes, lane/readability, original source PTS, and decoded BGR hash. The original reference and full journal rows are separately hashed. Reference declarations remain unauthenticated; human/field validation, physical calibration, strength, prediction and production eligibility remain false.

Match all rider proposals geometrically before scoring known clothing identities. Unknown candidates remain visible identity misses, with separate part-geometry counts. Report current-color and carried-color correct matches separately; unknown proposals cannot be omitted to improve detection coverage. All-six frames require exhaustive independent references for lanes 1–6. Continuity transitions cannot bridge missing/unlabeled frames, reference partitions/groups, source-time gaps or tracker camera scenes. Missing output remains explicit partial/unavailable input.

**Files:** `race_ai/boat_video_clothing_benchmark.py`, the public entry point in `race_ai/boat_video_benchmark.py`, `tests/test_boat_video_clothing_benchmark.py`, an integration test in `tests/test_boat_video_clothing_identity.py`, and usage in `docs/BOAT_VIDEO_MEASUREMENTS.md`.

**Verification focus:** unknown/extra parts; swapped clothing IDs; carried versus current evidence; source PTS/BGR/media mismatch; sparse labels; missing frames and scene/split boundaries; invalid number/geometry/semantics; input immutability; legacy hull scores.

- [x] Write meaningful failing tests for real clothing tracker output and the explicit rider reference interface; capture RED.
- [x] Implement the minimal offline scorer using existing matching/score arithmetic.
- [x] Verify identity/detection denominators and strict source bindings with adversarial controlled fixtures.
- [x] Run the unchanged legacy benchmark tests and the complete existing video regression suite. Record scope and any skips/failures.
- [x] Document new API, restored asset inventory and missing real six-boat/calibration proof. Deliver the local patch to the parent; no production integration or promotion here.

Verification: 56 focused tests, all 955 video tests with immutable parser/adapter bootstrap, the existing 221-test source unit step with stock Chromium headless-shell 1234, and 12 workflow-reference tests passed. No real six-boat/strength/calibration acceptance is claimed. The first unbootstrapped full run and missing-browser unit run failed; both environment causes were preserved in local logs and corrected without changing existing tests.
