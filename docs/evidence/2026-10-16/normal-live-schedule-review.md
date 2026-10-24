# Normal LIVE schedule reader independent review

Verdict: **PASS0 — no actionable findings.** Scope: new `race_ai/live_video_source.py` and `tests/test_live_video_source.py`, against base `2e392c78f8451762fc7cb6cfd5880464bd90955c`. No product files were changed by this reviewer.

## Behavior and safeguards

The reader constructs one exact public `/setting/live/{pinned stadium}/setting.json` URL from the existing venue mapping. The default transport uses the unchanged no-redirect fetcher, a 10-second transport timeout, and a 16385-byte detection read; accepted bodies are limited to 16384 bytes. Capture clocks must be ordered, remain on the requested JST date, and finish within the 10-second clock budget.

The top-level schema and all four rows are exact. Each row must use the matching br/mix source, live/dvr kind, observed tokyo region, pinned stadium, and exact reference form; DVR references include the requested JST date. Every window begins on that date, has a positive duration no greater than 24 hours, and matches its own live/DVR pair. Equivalent timezone representations normalize correctly. Unknown schemas/identities, duplicate JSON keys, numeric/nonfinite inputs where strings are required, malformed timestamps, invalid responses, and transport failures stop with fixed error codes.

The mix schedule status is limited to FUTURE/ACTIVE/ENDED schedule semantics. Results retain only bounded derived schedule/provenance fields and static public URLs, with no playback metadata/HLS/keys/media lease, race ID, phase identification, frame-clock mapping, or boat features. Race binding, exhibition detection, and wall-clock alignment remain UNVERIFIED; prediction eligibility is false and model validation remains UNVALIDATED. Unused registration text is not retained. Transport error text is suppressed.

The supplied public-route evidence constant matches the reported primary-JS SHA256 `eeb812473c139e2f32127b3e49774ffdeb48c97cef7821598e0e191f7ae465d8` and Omura route. This reviewer did not reacquire that JS or settings. Other venue paths are only synthetically verified and do not establish real settings/media availability. No VOD resolver/config/workflow behavior was modified.

## Verification executed

Fresh focused command:

```text
.venv/Scripts/python.exe -X utf8 -m unittest tests.test_live_video_source tests.test_exhibition_video_source -q
Ran 29 tests in 0.056s
OK
```

**18 additional independent synthetic probes passed**, final exit code 0:

- Exact10-second acceptance and 10.000001-second rejection; exact16KiB acceptance/hash and one-byte-over rejection; exact24-hour acceptance and one-microsecond-over rejection.
- Timezone-equivalent live/DVR pairs; illegal reference suffixes in all four rows; invalid update timestamp offsets or missing timezone; unused metadata text absent from output.
- Nested duplicate row keys and numeric row values rejected with sanitized fixed codes.
- The actual default `bounded_fetch` path ran through a fake in-memory urllib opener: exactly one GET to the pinned setting URL, one `NoRedirect` handler, timeout10, and readcap16385. No real network or playback call could occur in this probe.

`git diff --check` on the reviewed paths passed. VOD/config/workflow compatibility is supported by the unchanged existing files and the focused source regression suite; no unrelated completed jobs or broad test suite were rerun.

## Exact reviewed files and limits

| File | SHA256 |
| --- | --- |
| `race_ai/live_video_source.py` | `a3c1bb6f6cebd30a7b31cd3e3b6ccd8be3695fbd1ede5a2e3b7b2f26427ca0c1` |
| `tests/test_live_video_source.py` | `e8ab5ec2f813d4bb0d5abddfb4f4e92b10166d3fee5494debcf015b2c281e300` |

This is code and synthetic-transport verification. No live network/source/cloud write, official operation, media fetch, raw retention, or independent physical-clock validation occurred. The transport timeout and post-fetch clock rejection were tested; actual live-network latency was not measured. A consistent active public schedule does not establish playable pictures, race/phase association, exhibition occurrence, continuous coverage, frame timing, boat identity, performance, or prediction eligibility.
