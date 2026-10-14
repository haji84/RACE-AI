# Official day-data pipeline evidence — 2026-10-15

The implementation now connects the existing Tokuyama index collector to a
separately scoped official common-site detail collector, the approved local
day store, private Blob SDK upload/readback, and `/api/today`. No source rights
were granted, no automatic source schedule was enabled, and no official day
snapshot was published as part of this change.

## Implemented behavior

- `official_racelist_adapter.py` parses supplied UTF-8 HTML without networking.
  The schedule in the race content frame must establish the expected date and
  venue for all twelve race links, identify the selected race, and agree with
  the race tabs. The six entry bodies must agree on lane color/text,
  registration text/profile links, unique racer/motor/boat identities, and
  closing time. Malformed tables, stale/swapped identities, absent entries,
  conflicting links and duplicate allocations fail closed. Known missing
  statistics remain null. Explicit current-row withdrawal markers are retained.
- `official_racelist_worker.py` allows one bounded GET only after a reviewed
  `facts_ingest` record matches the exact dated race URL or the fixed venue
  scope `https://www.boatrace.jp/owpc/pc/race/racelist?jcd=18`. Tokuyama index
  permission does not authorize this separate source. The limit is 1 MB,
  timeout is 10 seconds, redirects are rejected, and capture occurs after GET.
- `collect_tokuyama_day` can optionally collect twelve details. It retains all
  thirteen source URLs, body hashes and actual capture times. It uses the
  existing name/race/lane join and retains closing times, boat numbers and
  available statistics. Candidates always have
  `redistribution_authorized: false` until the publisher validates approval.
- Multi-source publication requires the primary approval and an explicit
  matching entry in `source_approvals` for every additional source URL. An
  index approval cannot authorize common-site details. No approval switches or
  fabricated production records were added.
- `tokuyama_feed_pipeline.py` defaults to a no-network/no-write dry-run. Its
  explicit `--execute` path collects, validates and atomically stages approved
  data. `--upload-blob` additionally uses the existing private SDK roundtrip
  verifier and exact `race-ai/day/YYYY-MM-DD.json` key. Rights and approval
  files must be supplied by the operator; unavailable or unapproved data stops.
- `/api/today` uses `BlobClient.get(pathname, access="private", timeout=8,
  use_cache=False)`. The pinned PyPI `vercel==0.11.6` implementation returns
  `GetBlobResult.content: bytes`; it does not return the stream shown in some
  current web documentation. The API validates metadata, private origin,
  exact key, content type, bounded decoded content and declared size, full
  venue/race/lane identities, source hashes, publication flag and as-of times.
  It rejects duplicate JSON keys, nonfinite numbers, invalid UTF-8 emission,
  previous-day/future captures and JST-midnight crossings. Missing values are
  retained. It needs `BLOB_READ_WRITE_TOKEN` and `RACE_AI_FEED_APPROVED=1`;
  deployment OIDC alone is not a Blob read/write credential.

The SDK buffers the HTTP body before returning `.content`; the API's 6 MB
check bounds accepted/served content, not SDK network buffering. HTTP content
length may describe compressed bytes, so it and decoded bytes are bounded
independently. Permission for source publication and the feed environment gate
must remain unset until independently established.

## Verification evidence

58 targeted Python tests pass using `.venv/Scripts/python.exe -X utf8`, covering
the parser, scoped collector, index/detail bridge, publisher, pipeline and API.
Tests were written before each new implementation; missing modules/interfaces
and rejection gaps were observed failing before repairs.

The complete synthetic integration test performs thirteen injected source
responses -> twelve races/seventy-two lanes -> reviewed test-only publication
records -> atomic local JSON -> private SDK-shaped put/get/SHA -> `/api/today`.
It checks exact pathname, private access, no random suffix, overwrite behavior,
all source metadata and preservation of the twelve complete races. It is an
offline contract test; it is not evidence of cloud traffic or actual races.

Full-suite snapshot during parallel UI work: 254 tests ran, 252 passed, one
OpenCV-dependent test skipped and one existing mobile CSS assertion failed
while the UI stylesheet was being replaced. The failure was reported to the
UI implementation lane; a final shared-suite rerun is required after its write.

## Bounded official-source observations

On 2026-10-15 JST the requested Tokuyama `20261015` common-site 1R URL returned
HTTP 200, `text/html`, 13,995 bytes, with the explicit message
`データがありません。` and no entry table. HTTP success does not establish
race data or absence of an event; this body is rejected by the adapter.

A historical `20261014` Tokuyama 1R response returned HTTP 200, UTF-8 HTML,
69,928 bytes. Its SHA-256 was
`25cff9efa4a024f83d3e346444ba87d31e2d5996f79ed50b84cdeb06cbf86e7e`.
The observed structure contains six entry bodies and a closing time of 08:43.
An offline structural parser audit used an explicitly test-only matching
capture timestamp. Actual retrieval occurred on the following day, so this is
not valid current-day provenance and was not staged or published. The source
original was held only outside the repository temporarily and removed after
the audit. No source original is committed.

Still unproved: an approved actual current-day twelve-race/seventy-two-boat
Tokuyama collection, official B/K reconciliation for that same meeting, the
motor allocation cycle, current exhibition/result collection, all twenty-four
venues against actual pages, and real cloud publication/readback/API display.
The generic common-site parser accepts the twenty-four venue codes; that is a
structural capability, not a claim of twenty-four-venue live verification.
