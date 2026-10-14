# Official day-data pipeline evidence — 2026-10-15

The data lane now produces an owner-approved actual current-day nationwide
feed. The owner's factual-data attestation is recorded in
[DATA_PERMISSION_CONFIRMATION.md](DATA_PERMISSION_CONFIRMATION.md). It is an
operator attestation, not an independent legal audit; photograph and video
rights remain separate.

## Implementation

- `official_racelist_adapter.py` parses supplied official HTML without network
  activity. Date, venue and selected race must agree across the complete race
  schedule and tabs within one content frame. Lane text/color, registration
  text/profile links, unique racer/motor/boat allocations and closing time are
  checked. Malformed tables, stale/swapped identities, absent entries and
  conflicting links fail closed. Optional missing statistics remain null.
- `official_racelist_worker.py` performs one bounded GET only after independent
  source-scoped ingestion approval. Tokuyama index permission does not cover
  common-site details. Responses are capped at 1 MB with a 10-second timeout;
  redirects are rejected and capture occurs after the response.
- The existing Tokuyama worker optionally joins twelve official details through
  the existing race/lane/name join. It retains all thirteen source URL/hash/time
  records. Candidates remain unpublished until publisher approval. Its operator
  CLI defaults to a no-network/no-write dry-run.
- `official_day_schedule.py` verifies the current nationwide index's date title,
  full-year refresh URL, complete table/header/notes and each row's venue image,
  dated meeting and dated entry links. Only the verified complete day listing
  establishes non-listed venues as `NO_EVENT`. An empty page, truncated table
  or failed request cannot establish no event.
- `official_b_snapshot_adapter.py` reuses the existing registration/lane parser
  and offers strict program detail mode. It independently verifies Japanese
  full-year date headers, race headings, closing times and six distinct racer,
  motor and boat identities. Names, grade and available national/local/motor/
  boat statistics come from the program. B does not supply average ST or
  exhibition measurements; those fields remain null.
- `national_day_pipeline.py` checks the recorded operator review and performs
  exactly one current official index GET plus one current B archive GET. It
  extracts B safely in memory and reconciles venue codes with the schedule.
  Source HTML/archive/text is not saved. B failure preserves the verified
  schedule, marks active venues `ERROR`, and retains separate `NO_EVENT`
  states. Healthy, partial, missing and error states are independent.
- Multi-source publication requires a matching approval for every observed URL.
  The operator review can supply those records only for its recorded factual
  purposes and source scopes. Neither CLI adds a permission-granting flag.
- `/api/today` uses the pinned `vercel==0.11.6` `BlobClient.get` with private
  access, exact date key, eight-second timeout and cache bypass. The actual
  package returns `GetBlobResult.content: bytes`, not a stream. The reader
  validates private origin, exact key, JSON content type, byte/declared size,
  complete venue/race/lane identities and as-of times. It rejects duplicate JSON
  keys, nonfinite numbers, invalid UTF-8 emission, stale/future captures and JST
  midnight crossings. Empty venues require an explicit availability state and
  schedule source URL/hash/capture matching a unique top-level source record.
  Race program references receive the same association check. The complete
  active venue set must agree with the twenty-four venue states.

The API requires `BLOB_READ_WRITE_TOKEN` and `RACE_AI_FEED_APPROVED=1`; deployment
OIDC alone is not a Blob credential. The SDK buffers the HTTP body before
returning content, so the API's 6 MB cap bounds accepted/served content rather
than SDK network buffering. Compressed HTTP content length and decoded content
are bounded separately because equality is not guaranteed.

## Actual current-day verification

The explicit two-request CLI completed on 2026-10-15 at approximately 03:17 JST.
The approved output passed the same `api.today.validate_feed` used by the API.
It contains 13 `READY` venues, 11 `NO_EVENT` venues, 156 complete races and 936
boats. Index and B active codes agree exactly:
`02,04,06,10,11,12,13,14,15,20,21,22,24`.

The current-day index was captured at `2026-10-14T18:17:19.816293+00:00`, SHA-256
`7ee7d1d5981f67040995407ae43055c3b5ea9e49458ca0f643d46ba199de8232`.
The B archive was captured at `2026-10-14T18:17:29.157972+00:00`, archive SHA-256
`d1943dbff930d78a76c1342858b20ff5fefcbaf51b3dae52b24ecc5e2747d5ef`,
extracted text SHA-256
`17044ffb0bb9a74852a59e31123e630efabc58186d8dad63d6bd38ef241f6998`.
The approved payload SHA-256 was
`5438656a8a2844ba2ab18c520759c38f90912ac5fb3af2c24cdc67c1d0d0c4a7`.
Cloud publication/readback/API display are tracked by the root's separate live
E2E evidence; these local collection facts do not claim those cloud operations.

Reproduction:

```powershell
.venv/Scripts/python.exe -X utf8 -m race_ai.national_day_pipeline --date 2026-10-15 --review config/operator-official-facts.json --output <protected-output-path> --execute
```

Omit `--execute` for a no-network/no-output dry-run. No upload or manual race
input is required by this collection command.

## Test evidence and limits

72 targeted data-lane Python tests pass with `.venv/Scripts/python.exe -X utf8`.
Each new parser, worker and pipeline interface was first observed failing its
new tests, then implemented. Rejection regressions cover stale/duplicate/swapped
identities, malformed tables, scopes, provenance, timestamps, missing values,
no-event/error distinctions and SDK response semantics.

A synthetic thirteen-source -> twelve-race/seventy-two-boat -> approved local
store -> SDK-shaped private put/get/SHA -> API test passes. It is an offline
contract test, distinct from actual collection and real cloud E2E.

The last clean shared suite before integration ran 296 tests: 295 passed and
one OpenCV-dependent test skipped. A later run coincided with temporary
conflict markers in root-owned authentication files; the root was notified.
Run the final shared suite after integration.

A bounded Tokuyama 20261015 detail URL returned HTTP 200 with the explicit
message データがありません。 and no entry table; it was rejected. The verified
national schedule subsequently established that Tokuyama is not scheduled on
this day. A historical 20261014 Tokuyama 1R body (69,928 bytes, SHA-256
`25cff9efa4a024f83d3e346444ba87d31e2d5996f79ed50b84cdeb06cbf86e7e`)
was used only for a structural parser audit with an explicitly test-only
matching capture timestamp. Actual retrieval was on the next day, so it was
never a current-day candidate or publication. Its original was removed.

Still unproved: same-meeting B/K/result reconciliation, motor allocation cycle,
current exhibition/result collection, and individual live detail validation at
all twenty-four venues. The generic detail parser accepts twenty-four codes;
that capability is not a claim of twenty-four-venue detail-page verification.
