# Measured BOAT history: course, ST, status and source lineage

Goal: preserve the real measurements already parsed by PR64 when preparing
future model inputs. The existing legacy model projection intentionally drops
actual course and nonnumeric dispositions; this separate API retains them.
It is a source adapter, not another prediction model or permission service.

```python
project_boat_course_history(
    rows, source_records, *, event_date_jst, as_of, racer_ids
)
```

Rows are the unchanged PR64 `parse_k` fields plus `source_sha256`. Source
records bind the exact K URL, archive date/hash, nullable original
`published_at`, and actual `captured_at`. Six distinct racer IDs select a
measurement cohort; their presence does not prove a future race's roster.
Inputs remain unchanged. Supplied metadata consistency does not authenticate
the source bytes, publication, clock or rights.

The adapter verifies the exact PR64 core code at
`761247bee0209e37b1af6b8885e92cad3e9260a5` and reuses its existing
`summarize` arithmetic. It does not replace PR64 code or the legacy projection.

## Selection and measurements

1. Select the latest whole source visible by capture at the requested as-of,
   comparing aware timestamps as UTC instants. Different contents tied at the
   latest capture are ambiguous. A newer empty or unknown-publication source
   never fills its omissions from an older revision.
2. Exclude target-day and future results. Original publication must be known
   and no later than capture/as-of to enter qualified statistical windows.
   Unknown publication remains `None` in raw diagnostics only. Neither midnight
   nor capture time is substituted for original publication.
   Claimed publication/capture before that K source's JST event-day start is a
   detectable contradiction and is rejected. This lower bound is not an actual
   race time or a claim of source finality.
3. Preserve lane separately from actual course, numeric ST separately from
   F/L/MISSING, and ABSENT separately from an actual start. ABSENT appears in
   diagnostics but enters no window. A genuinely measured OK/ST0.00 is zero;
   missing observations are never converted to zero.
   Every non-ABSENT parser row must carry an actual course in1..6; `None` is
   accepted only for ABSENT, matching the fixed parser's record contract.
4. Reuse overall10, lane10 and actual-course5/10/20 summaries. Keep requested
   versus actual sample size, valid numeric ST, valid finishes, dispositions,
   selected row references and incomplete-window status visible. PR64's
   existing first/top3 denominator is every selected start, including unknown
   finishes; it is not a calibrated win probability.
5. PR64 `race_at` is a date sentinel. Date/race-number order is not an actual
   event timestamp. Mixed venues for a racer on one day withhold chronological
   windows explicitly; they are not reported as empty history or backfilled
   with older starts.

The output is `RACE_AI_BOAT_OBSERVED_COURSE_HISTORY_V1`, with scope
`DESCRIPTIVE_MEASUREMENTS_NOT_FORECAST`. It supplies neither latent stamina,
tactical adaptability, relative-wind geometry nor a water-wetness rating.
FULL75, model weights/IDs/roster, old forecasts, and the C/P/E/public owners
remain unchanged. A later scoring or feature-requirement change needs its own
concrete design and the existing Owner Gate.

## Acceptance boundaries

Focused tests include fixed actual PR64 parsing of authored K text and exact
statistic reuse, status/course/sample distinctions, source revisions and
omissions, UTC offsets, missing publication, target-day leakage, bounded native
types, deterministic ordering and input preservation. Such records remain
fictional test inputs. Existing reference-complete CI discovers these tests;
no new workflow or collector is introduced.

A separately reviewed one-shot NEW K24 RAM parse can provide real measurement
wiring evidence, using the existing bounded official-facts scope and strict
transport. It must preserve unknown publication and report only hashes and
aggregate counts. It is not a prospective forecast, pre-cutoff freeze, genuine
receipt, scientific model improvement or 98% acceptance. The caller, one-attempt
record and later actual outcome belong to separate private evidence; no source
archive, individual table or original HTML is committed here.

Owner device and account/cost acceptance remains deferred. Source-purpose,
public release, security, paid-resource and main/independent-review gates remain
in force. Held33 and the original stopped nonce stay unchanged.
