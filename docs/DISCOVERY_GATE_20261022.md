# 2026-10-22 P0: coverage reconciliation and rights admission (not a real E2E)

Issue #67: https://github.com/haji84/RACE-AI/issues/67

## What was independently checked

- Existing PR #71 includes **322 provisional audit rows, 29 listed venues**: boat 14/168, keirin 9/86, autorace 2/20, local horse 4/48. Its counts come from unverified provisional rows; no outcome or real forecast was recorded.
- Within each listed venue, rows form a contiguous 1..max race-number sequence. This is **not** a proof that every official race or venue has been found.
- The BOAT RACE official landing page lists 14 active venues for 2026-10-22 (https://boatrace.jp/). The Keirin CTC 2026-10-22 schedule page lists nine venues (https://keirin.ctc.gr.jp/schedule/), but the venue-specific actual number of races needs individual confirmation.
- The autorace official network lists Iizuka Oct20–22 and Isesaki Oct21–25 (https://fc.autorace.jp/); no real schedule rows or source media were copied here.
- The local horse calendar lists Monbetsu, Urawa, Kasamatsu, Sonoda (https://nar.sp.netkeiba.com/top/calendar.html?mode=kaisai&month=10&year=2026), a third-party reference, not a permission grant; central/local and cancelled offerings remain explicit unknowns.

These are human-readable coverage research observations, **not permission for automated harvesting or bulk-data storage**. All official race cutoffs, final 3連単 offerings and all actual real forecasts remain unverified here.

## Permission gate: do not conflate browser access and data rights

| Source | Source policy checked | Collect programmatically | Save/train/republish |
|---|---|---|---|
| BOAT RACE | https://www.boatrace.jp/owsp/sp/extra/policy.html, no blanket reuse permission | NOT_ADMITTED for new pipeline | NOT_ADMITTED pending exact grant |
| AUTORACE.JP | https://autorace.jp/policy/, prior authorization required for reproduction/transmission | NOT_ADMITTED | NOT_ADMITTED |
| Keirin schedule/CTC | Official schedule visible; machine-use and each downstream purpose not verified | NOT_ADMITTED | NOT_ADMITTED |
| Local horse calendar | Third-party listing visible; training/bulk retention rights not verified | NOT_ADMITTED | NOT_ADMITTED |
| JRA central | No meeting inferred merely from Thursday/date; separate source/policy evidence required | NOT_ADMITTED | NOT_ADMITTED |

Use a scoped, dated, verified license with allowed source/fields/collection/storage/training/display/fees and expiry before approving **each** automated adapter. Existing PR #64 owner-approved boat activity is distinct, may not be copied as blanket rights approval or repeated while STOPPED_UNCERTAIN_POST.

## Code / verification scope

`race_ai.discovery_reconcile.compare_daily` compares an explicitly entered reference to an AUDIT_ONLY ledger without any network, paid provider, model invocation, or mutation. Missing venue, missing numbered races, unlisted venue/races, unknown race counts, unknown cutoffs and missing NO_FORECAST reasons are output separately. The module makes no official-coverage, rights, or pre-cutoff-freeze assertions: corresponding flags always false.

Use **only manually authorized or synthetic reference inputs**; `MANUAL_REFERENCE_ONLY` explicitly cannot grant ingestion rights. No assumption of 12 races per venue. Tests use fictional 2030 venues; no source data gets committed. No scheduler or production prediction will be enabled by these changes.

## Remaining acceptance gates

1. Obtain appropriately licensed machine-readable 4-sport schedules, verify all race numbers and official sales cutoff times with timestamped independent witnesses; compare daily and alert on omissions.
2. Get scoped rights for entry/feature data, isolate odds/market features, train/select models and run actual forecasts without current/future result leakage.
3. Admit a real append-only store and verify an independent immutable external receipt **before** each official sales cutoff. Static timestamps, booleans, Git commit author dates and synthetic tests are **not external attestation**.
4. Record NO_FORECAST with reason for unavailable/blocked/late records; settle independently verified official results including modifications; compute all-evaluable Hit@8.
5. Perform the actual per-sport, in-time, forward real-data E2E. Until then status is **UNVERIFIED** and Hit@8 is **not computed**.
