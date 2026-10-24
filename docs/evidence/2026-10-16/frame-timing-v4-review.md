# Frame timing v4 independent review

Result: **PASS0 — no actionable findings** in the requested changes.

Reviewed on 2026-10-16, branch `codex/race-ai-completion`, against base `2595f37a04d51606e2fd4576876dc663bdd462aa`. Scope is the uncommitted `race_ai/video_frame_timing.py`, additions in `race_ai/exhibition_video_decode.py`, and `tests/test_video_frame_timing.py`. Existing fixtures and the lease wrapper were read only to verify integration and failure behavior. Product and test files were not modified by this reviewer.

## Findings

No P0, P1, P2, or P3 findings remain. The current version includes the author's two refinements made during review: huge integer durations fail before `math.isfinite` can overflow, and failed/insufficient assessments expose no PTS digest or usable timing prefix.

The implementation observes every decoded frame before sparse image sampling. PTS and time-base checks bound arithmetic, and successful summaries retain exact rational spans and minimum/maximum intervals. Duplicate, reversed, changed-time-base, invalid, count-bound, and exclusive-duration failures suppress the entire segment's usable timing fields. Segments have independent assessors, including across declared discontinuities; no cross-segment interval or constant-frame-rate/missing-frame estimate is invented.

Returned derivatives contain bounded per-segment summaries without frame lists, pixels, media bodies, keys, or URLs. A consistent decoded PTS sequence remains explicitly insufficient to verify source completeness, independent clocks, physical exhibition time, or prediction eligibility. The existing `UNVALIDATED`, unverified boat/world calibration, and empty `boat_features` gates remain intact. No source, authentication, caller, workflow, or prediction-path changes are present in the reviewed product diff.

## Verification executed

Fresh final command with `RACE_AI_REQUIRE_VIDEO_RUNTIME=1`:

```text
.venv/Scripts/python.exe -X utf8 -m unittest tests.test_video_frame_timing tests.test_video_program_clock tests.test_exhibition_video_decode tests.test_exhibition_video_camera_integration -q
Ran 49 tests in 0.834s
OK
```

The final run covers the latest two refinements, uses the installed PyAV runtime, and reports no skips.

Independent in-memory probes, final exit code 0, **19 checks passed**:

- Eight exact canonical-JSON byte comparisons loaded the decoder source directly from the base Git object and compared it with current omitted/false `frame_timing` across default, camera-only, program-clock-only, and combined options. All result bytes and snapshot IDs were equal.
- Four synthetic PyAV integration cases introduced a duplicate, backwards PTS, time-base change, or exact exclusive segment-end timestamp after a valid prefix, including frames skipped by image sampling. All frames were counted; aggregate timing was unverified; every usable timing field and the digest were null; existing output gates were preserved.
- Two synthetic PyAV integration cases omitted PTS or time base. The existing lease error-redaction wrapper rejected processing without returning partial derivatives. The initial exploratory probe expected an internal error code; it was corrected to assert the existing public `VIDEO_TRANSIENT_PROCESSOR_FAILED` code before the successful final rerun.
- Four pure-assessor cases checked the accepted/rejected rational time-base boundary and near-int64-limit PTS arithmetic.
- One pure-assessor case checked `10**1000` duration rejection without `OverflowError` and with no digest.

`git diff --check` on the reviewed paths completed successfully (only Git's existing LF-to-CRLF notice).

## Review limits and exact files

This is focused code and synthetic-media verification. No network requests, credentials, real-media/source jobs, full legacy jobs, repository-wide suite, or external physical-clock validation were run. Timing consistency intentionally establishes only relative PTS quality within decoded segments; it does not establish source frame completeness or first-media-sample alignment. Existing parsed segment durations remain the integration input.

SHA256 of reviewed final files:

| File | SHA256 |
| --- | --- |
| `race_ai/video_frame_timing.py` | `7d74942bb32439b0f78dc2a676faf034e315576f4b69e12b81ca7fa444c5c0c6` |
| `race_ai/exhibition_video_decode.py` | `e9333d03fcdd5d76dcf84fb5cc5a15d79ba0709bdf47c27ddfd60d45cb45944f` |
| `tests/test_video_frame_timing.py` | `80f8c215961cc1c3d3481ec8231385e70f541c6629fa5391527b80c190b1d16c` |
