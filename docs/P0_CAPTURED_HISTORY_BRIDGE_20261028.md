# Captured single-day BOAT history bridge

## Goal and Done

Connect already measured K facts to the two existing missing-aware pairwise
research models without changing either model, its weights, or saved forecasts.
Done means an offline adapter, independently checked arithmetic and lineage,
adversarial tests, existing-model integration, and a retained real-input replay.
Replay is development evidence, never a backdated pre-cutoff prediction.

## Contract

`build_program_history_snapshot(program_race, program_source, history_rows,
history_source, *, event_date_jst, as_of, race_revision)` returns a detached
`snapshot` in the existing observed-pairwise schema and a separate private
`history_audit`. Reuse `build_program_snapshot` for B identity and rate facts.
Reuse the strict K row/source validation in `boat_observed_course_history`;
its publication-qualified projection and existing callers remain unchanged.

The history source has the same seven fields as an observed-pairwise source.
Its URL must be the exact dated official K archive URL. One explicitly selected
whole K-day version is supplied per call, with one source ID/hash/rights reference.
No silently combined days, inferred source, older revision fill, or truncated
latest-N selection. All supplied rows must bind that source and day. Bound input
to 1,728 rows; each represented race must have all six unique lanes and racer
identities, unique actual courses for starters, and no duplicated numeric finish.
An exact repeated row may be deduplicated; conflicting duplicates are rejected.
Registration identities are four ASCII digits, matching the unchanged model.
Duplicate rows must also agree in canonical JSON; differently signed zero
duplicates cannot select different membership hashes based on input order.
This checks represented races, not the completeness or finality of the source day.

The K day must precede the target JST day. Capture must be on/after the source
JST day start and no later than `as_of`; B capture and `as_of < planned cutoff`
remain enforced by the existing bridge. Unknown publication remains null with
`CAPTURED_BY_CLAIM`. Known publication uses `SOURCE_PUBLISHED_AT_CLAIM` and must
be on/after the source-day start and no later than capture. These are supplied
claims, not authenticated clocks or permissions. Parser midnight stays a date
sentinel. A later caller supplies its real current clock; this API grants no
historical prediction, freeze, source-rights or publication authenticity.

For each target registration, select all its starts in that one source day.
ABSENT records are excluded from start denominators but retained in diagnostics.
There is no claimed chronological latest-N ordering. A racer appearing at more
than one venue on that day is rejected as ambiguous identity. Windows bind the
day, source hash, registration and a canonical digest of the full supplied,
deduplicated row membership. Dropping a complete six-row race changes that
digest; the adapter cannot authenticate that supplied membership is the whole
archive. The policy is `ALL_SUPPLIED_STARTS_IN_SINGLE_SOURCE_DAY`.
Row references retain lane separately from
actual course and include the source hash; detailed measurements stay private.

* `recent_mean_finish`: emit only when every selected start has a numeric finish
  and no F/L disposition. Otherwise preserve an explicit missing reason. Counts
  describe numeric finishes, not the ST classification.
* `recent_mean_st`: average only numeric OK ST, retaining total/OK/F/L/MISSING
  counts and actual `sample_n=ok_n`. A true 0.00 remains zero. All non-OK yields
  no feature; it is never zero-filled. ABSENT enters neither mean.
* Empty history remains `NO_PRIOR_SAMPLES`. Unresolved finish observations remain
  `UNRESOLVED_DISPOSITION`. No course, exhibition, wind, latent rating or sample
  denominator is invented. Existing B aggregate sample counts remain null.

Use the existing `strict_numeric_finish_mean_v1` and
`strict_ok_start_mean_seconds_v1` transforms and unchanged history-count fields.
Use exact rational decimal summation before converting the mean to float.
The returned source list binds both B and K without duplicate IDs, URLs or hashes.
Return the selection policy, all selected row references/status counts, both
feature dispositions and false source/clock/rights/finality/official-forecast
verification flags in `history_audit`. Inputs must not be mutated or aliased.
No source access, file writes, inference, training or forecast persistence occurs
inside this adapter. No result of the target race is an input.

## Validation and boundaries

Use fictional fixtures for malformed inputs, source mixing, all dispositions,
complete versus incomplete races, dates/offsets and exact boundary times. Run the
result through the already pinned PR71 observed-pairwise models with an explicit
analysis callback. For retained real K25/K26 input, verify exact source bytes of
the retained normalized files, original capture and all arithmetic independently.
A retrospective development replay declares `information_as_of` separately from
actual `executed_at`, preserves the original race day/cutoff, and holds races
already closed at that information context. It reads no target-result labels,
reports no accuracy and makes no old pre-cutoff generation claim. All19 slots
remain in its caller/report: models not executed in that replay remain explicit,
and old frozen forecasts are not combined with new inputs as a paired comparison.
Do not rerun downloads or rewrite the old prediction seals. A current-day
forecast needs a separate reviewed, capped caller and fresh B source if available.

All19 registry slots and the 15 unavailable model IDs stay visible. This adds
measured inputs to two models; it does not establish a new model, accuracy gain,
FULL75 readiness, real pre-official-cutoff freeze or 98% acceptance. Existing
held33, old predictions and result failures remain unchanged. No main merge,
deployment, paid service, expanded source right, automatic source schedule,
device acceptance or cost acceptance is part of this unit.
