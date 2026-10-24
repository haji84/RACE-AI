# Source-declared exhibition media clock v3

The owner requests independently saved before/after exhibition forecasts and actual video analysis. Existing v1/v2 video derivatives use relative segment PTS, color candidates and optional image-space camera estimates. The retained prior HLS profile contains explicit PROGRAM-DATE-TIME tags. This bounded addition assesses those declarations; it does not establish the provider clock, the physical exhibition event, the first decoded video-frame time, boat identity, surveyed water-plane geometry or predictive value.

The owner has authorized autonomous implementation, tests, independent review and protected Preview verification in the completion branch. Keep all historical snapshots, namespaces, times, raw B names and dedicated workflow/auth settings unchanged. No generic design-approval pause is needed within that scope.

## Interface and limits

`race_ai.video_program_clock.assess_program_clock(raw, segments, *, closed_at, captured_at)` is pure and performs no I/O. Inputs are the already resource-scoped child playlist and exact minimal segment dictionaries with sequence, duration and discontinuity. Return only hashes, counts, fixed status/scope strings and bounded UTC segment-boundary rows. No original manifest, locations, keys, tokens, frames or media are returned.

Maximum raw bytes1MiB, lines2500, segments100, individual duration20 seconds and summed duration600 seconds. The complete VOD must have one header, one VOD declaration, one media sequence and a final ENDLIST. Known malformed/duplicate clock and structure tags reject. Optional discontinuity-sequence metadata remains valid and distinct from a discontinuity event.

Require an explicit timezone-aware timestamp for every segment. Lexically enforce valid offset minutes00–59, hours00–13 or exact14:00, calendar validity and at most6 fractional digits before UTC conversion. Require declared segment dates on the actual race's JST date, ends not after the actual child-playlist capture, and ends strictly before the official cutoff. Source captures after close can inspect earlier declarations but never become preclose forecast inputs.

No timestamp interpolation. Parsed sequence/duration/discontinuity must equal the existing scoped parser's metadata exactly. Calculate duration with Decimal microseconds. Reject all overlaps. Retain a forward rounding gap up to1ms explicitly; larger gaps require an explicit discontinuity. Any invalid suffix or missing anchor removes all usable boundaries, rather than promoting a valid prefix.

## Decoder integration and truth boundaries

`analyze_exhibition(..., program_clock=False)` keeps the old default signature semantics and output bytes. False/default v1 and camera-only v2 do not call the new assessor or add fields, clock reads, source requests or dependencies. Exact boolean True adds `program_clock` and analysis version `transient-hls-color-candidates/v3`; the snapshot hash binds the full result and the report binds the exact child-playlist SHA.

The program clock describes WHOLE_PLAYLIST_METADATA_NOT_DECODE_COVERAGE. Existing COMPLETE/PARTIAL playlist decode coverage remains separate. Decoded PTS remains relative; do not equate a segment's first media sample with its first decoded video frame. Every result keeps independent_clock_verified=false, physical_exhibition_time_verified=false and prediction_eligible=false. Boat identity/camera calibration remain UNVERIFIED and boat features remain empty. No new forecast model or recommendation is created.

Primary technical reference: [RFC8216 sections4.3.2.6 and6.2.1](https://www.rfc-editor.org/rfc/rfc8216#section-4.3.2.6). Those sections define an informative first-media-sample mapping and prohibit ambiguous mappings; they do not authenticate the provider clock or identify a physical event.

## Verification and live boundary

Observe a missing-assessor red test, then focused unit and actual synthetic MPEG-TS integration tests. Verify malformed tags, invalid offsets, unknown timezones, exact decimal arithmetic, whole-vs-partial coverage, overlaps/gaps, wrong-day/future/postcutoff declarations, metadata/count/size bounds and legacy full-output equality. Independent review found two P2 gaps in the first implementation; both must retain their regression tests and resolved review record.

Run the full Python and browser suites, latest-head Windows/Linux CI, and the protected Preview APIs with full-byte comparison. A new permitted clip may be processed only through the existing exact public-player scope, using RAM-only resources and a fresh current-day/cutoff check. Completed old clips are not reacquired to manufacture a v3 live example.

At07:34 JST16th, the exact Naruto1R beforeinfo probe was PENDING with OFFICIAL_PREVIEW_EMPTY_EXHIBITION_GRID. Its recording-index attempt returned VIDEO_SOURCE_AUTH_UNAVAILABLE; no playback media was requested. Preserve that error as an error, not a missing/publication proof. Numeric publication, new v3 real-media verification, independent physical-event timing, surveyed geometry and actual boat identification remain separate pending measurements.
