# P0 current-day private reader repair

`web/api/today.py` reads the exact `race-ai/day/YYYY-MM-DD.json` key for the
current JST day using the installed `vercel==0.11.6` SDK:

```python
async with AsyncBlobClient(token=blob_token) as client:
    response = await client.get(key, access="private", use_cache=False, timeout=8)
```

Only `BLOB_READ_WRITE_TOKEN` authorizes the store read. OIDC tokens and a
hand-built private host URL are not used. The API never writes, lists, probes
alternate dates, or falls back to an older snapshot. The response remains
`Cache-Control: no-store`.

The publication gate remains closed unless an authorized operator has set
`RACE_AI_FEED_APPROVED=1`. This repair does not change environment settings,
approve data rights, or establish a live feed. The reader requires the
snapshot's publisher-supplied redistribution flag and provenance; independent
permission evidence remains the separately reviewed publisher's responsibility.

The private SDK returns `GetBlobResult.content` as bytes, not a stream. Both
returned content length and declared SDK size are checked against 6,000,000
bytes before JSON parsing. SDK 0.11.6 buffers the download before returning, so
this cap bounds accepted/published content, not network transfer or peak SDK
memory usage. Oversized publisher output must also be rejected before upload.

The web deployment root excludes the research package. Its self-contained
validator follows the existing publisher/browser contract: current JST day,
non-future timezone-aware observation and optional upstream publication time,
HTTPS source identity and SHA-256,
approved redistribution, bounded venue/race/boat collections, matching race
date and venue, unique venue/race/lane identities, unique racer and nonnull
motor identities within each race, and consistent counts. Nonnull result
course/start/finish fields require explicit result availability. Root
`previews`/`results` count races whose corresponding availability flag is true,
matching the normalizer's contract; they do not count individual boat fields.
A read crossing JST midnight is rejected. Malformed,
duplicate-key, and nonfinite JSON are rejected. Known normalized public fields
are preserved while unknown fields and private annotations at each level are
omitted from the API response.

Offline tests use synthetic data, the actual pinned SDK result dataclass, and
the existing normalizer/publisher contracts. They prove the SDK call shape,
explicit token selection, error handling, validation, projection, and lack of
writes/fallback. They do not prove access to any live Blob store, the current
deployed route, source rights, or successful production publication.

Validation command:

```sh
python -m unittest discover -s tests
```
