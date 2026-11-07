# Local private whole-wire vault candidate

## Goal and limits

Implement an additional storage-only primitive in the PR71 owned worktree at
`db075c203704d2b30df5742ce8458a43932696a4`. Preserve the original typed model
wire as opaque bytes in a new local SQLite database using the D1 prepared
statement / transactional batch shape. This selects no actual Cloudflare
database, destination, access policy, credential or cloud resource.

Do not connect a write call to the Race33 reservation, admission or public
dispatcher. A reservation is not a consumed private-write permit. Operational
private-action ownership and genuine protected readback / independent receipt
remain separate unmet gates. Without those gates the result is
RETENTION_UNVERIFIED and public submission remains denied. No HTTP listener,
Wrangler config, provider collection, schedule, deploy, account/cost check,
device acceptance, odds/model change or main integration belongs to this unit.

## Fixed interface

The production module exports two operations:

* `createLocalPrivateWire(binding, expectedClaim, originalWire, admitWrite)`
* `readLocalPrivateWire(binding, expectedClaim, admitRead)`

`binding` is an explicitly supplied prepared-statement / batch-shaped local
candidate binding; it has no default endpoint, URL, arbitrary SQL option,
alias, list, latest lookup or fallback. The test-only native Node SQLite
adapter opens lazily, outside every Git checkout. A read never creates a file,
schema, metadata or chunk. Admission is required and returns exactly `true`;
missing, false, truthy, thrown or argument-mutating admission denies before
any binding call. Snapshot the claim and wire before callbacks; callback
arguments are owned claim copies (`admitWrite(ownedClaim)` or
`admitRead(ownedClaim)`); changes to those copies must be detected. Do not
expose the wire to the admission callback. Bound the original
inputs before any copy or hash. Return fixed safe error codes without opaque
proofs, wire fragments, paths or underlying SQL error messages.

The exact plain-data claim has only these keys:

| Field | Contract |
| --- | --- |
| schema | `RACE_AI_LOCAL_PRIVATE_WIRE_CLAIM_V1` |
| destination_contract | `LOCAL_SQLITE_D1_BATCH_CANDIDATE_V1` |
| destination_ref | `local-private-vault-` followed by 1..64 lowercase ASCII letters, digits or hyphens; compatible with the existing R/C reference grammar |
| owner_ref | 1..128 printable ASCII characters, no leading/trailing whitespace |
| request_sha256, wire_sha256, delivery_sha256 | lowercase 64-hex |
| model_source_sha40 | exact lowercase 40-hex Git pin from the original case; do not invent a SHA256 pin |
| retention_request_sha256, reservation_sha256, reservation_row_sha256 | lowercase 64-hex from the existing R/C/C-row seam |
| reservation_commit_guard_at, retain_until | strict valid UTC ISO `YYYY-MM-DDTHH:mm:ss`, optional 1..6 fractional digits, then `Z` or `+00:00`; retain_until strictly later than the guard |
| protection_policy | `LOCAL_INSERT_ONLY_SQL_V1` |
| wire_bytes | integer 1..4,194,304 |
| chunk_sha256 | exact ordered lowercase 64-hex digest array, length ceil(wire_bytes / 524,288) |

Reject extra keys, accessors, symbols, nonplain objects, invalid scalar types,
invalid dates and oversized metadata. Canonical claim JSON sorts keys and is
at most 8KiB. The locator is SHA256 of a fixed version domain plus the whole
canonical claim, binding destination/owner/R/C-row/horizon as well as the
wire. The module verifies bytes, chunk hashes and whole SHA, not authenticity
of these declarations. It does not decode the typed wire, infer permissions,
mint receipts, sign claims, create timestamps or renew retention. Preserve
the exact original timestamp strings and compare at microsecond precision;
never round or truncate an original guard to JavaScript milliseconds.

Return qualified LOCAL_ONLY metadata, exact copied bytes for readback and an
explicit false independent-retention-proof flag. A known successful equal
create can use exact readback only, changing no bytes or times. An unequal
existing identity stops. No internal write retry occurs, including after a
batch error or failed acknowledgment. A caller facing uncertainty must use
only the exact read operation; missing/incomplete/denied read is UNRESOLVED,
never authorization to create again. This unit does not pretend to enforce
cross-call private-action consumption in the current attempt owner.

## SQL and resource boundary

Use exactly two versioned object/chunk tables in a new dedicated schema, with
exact known schema/trigger definitions checked before use. Initialize only a
truly empty admitted store. Refuse foreign, partial or changed schema without
migration, adoption, repair or dropping data. Assert schema admissibility
inside the same initialization batch before any DDL, not only a pre-read that
could race. Concurrent initialization may accept the exact same schema only.
Cooperative SQL constraints and
UPDATE/DELETE triggers enforce create-only rows. A privileged administrator
can bypass them; they are not independently enforced WORM/retention lock.

The atomic write is one bounded batch for metadata plus all chunks. Metadata
`ON CONFLICT(locator) DO NOTHING` establishes this batch's ownership via the
same connection's SQLite `changes()` result; only a new metadata row may
insert chunks. Existing metadata skips every chunk, even if incomplete.
Use plain chunk INSERT (no IGNORE/REPLACE), either one bounded multirow insert
or a strict 1/0 `changes()` chain. Verify the exact result pattern, with no
interleaved statement calls on that batch connection. Use
conflict semantics that permit concurrent exact equality but never partial
repair, overwriting, extra chunks or cross-scope deduplication. Validate all
batch results and exact readback; failed partial execution rolls back. A
completed object cannot acquire additional or out-of-range chunk ordinals.
At most 32 objects and 16MiB declared wire bytes per local candidate store;
these are experiment caps, not account allowance or a physical file-size cap.
Enforce them atomically in SQL; an equal replay remains read-only at the cap.

Preflight fixed bounded metadata, chunk count/ordinals/types and lengths
before fetching any body. SQL must exclude oversized or type-invalid bodies
from materialization. Use at most 8 chunks, each at most 524,288B, verify every
chunk SHA and exact whole length/SHA, and use an atomic consistent read batch
or equivalently protected immutable pinned read boundary. Do not assume a
Python transaction spans Worker awaits, and do not fetch all bodies before
checking their declared size. The native adapter uses real SQLite transactions
for the batch shape, never a Map-backed pretend database. Node24 is the local
test runtime; deployed D1/Workers CPU, memory and API compatibility remain
unverified.

## Reuse and evidence

Reuse the chunk geometry and hash/readback pattern from the read-only original
dirty checkout, without importing or modifying that checkout:

* object-store.mjs: `158eec1b36430f4fc947f1edfb4b43700770d88ee11be7c9458ff65586967f46`
* schema.sql: `4311b6fbf29d2b186b24954fa94a963cd49b2aabfc19760ba3e5bf1379f78d86`
* local/d1-adapter.mjs: `ea61c5e221d54d3a88de5b8d1baf7f61b5ffb98620cdfa403b150ad591f3d4a0`
* import_snapshot.py: `76b81f8d53ea0795725b56debe6fa7d8ab61ad709cc622a935ae4f397a627e8c`

Do not reuse odds UPSERT/lease or historical aliases. Original source/save/
receipt/import times, held33, the original 409 predictions and model assets
remain unchanged. Existing saved original V1/V2 fixture wires are read-only
test input; no producer rerun is needed. Whole-wire roundtrip does not attest
source rights, actual publication, performance, a genuine receipt or accuracy.

Current official API references retrieved for this candidate on 2026-10-26
JST: [D1 batch](https://developers.cloudflare.com/d1/worker-api/d1-database/),
[BLOB conversion](https://developers.cloudflare.com/d1/worker-api/),
[row limits](https://developers.cloudflare.com/d1/platform/limits/).
The documented 2,000,000B row/BLOB limit motivates chunks; local batch tests
do not prove production behavior or free-plan feasibility.

## Done evidence and allowed paths

Local integration must show saved original V1 and V2 opaque wire roundtrip
from the existing ignored private fixtures, without copying them into this
public repository or claiming this private-input check ran in hosted CI.
Hosted CI runs the public deterministic binary tests; the single-chunk
original fixtures and eight-chunk binary evidence remain separate. Tests show
deterministic binary boundaries through 4MiB/8chunks; early oversized/type/
claim/capability refusal; equal replay; conflict; full middle/final batch
rollback; real two-process overlap; process death before and after COMMIT;
lost acknowledgment followed by read only; missing/incomplete/corrupt/
misordered/wrong-scope/oversized data with bounded materialization; exact
foreign-schema refusal and safe logs/errors. Report tested runtime and all
unmet stronger gates. Independent technical review is not formal GitHub
approval. Keep previous failures and repairs as separate evidence.

Allowed tracked paths are this spec, its plan, `workers/private_wire_vault.mjs`,
`workers/private_wire_vault_schema.mjs` (fixed executable SQL definitions),
`tests/support/local_private_wire_d1.mjs`,
`tests/private_wire_vault.test.mjs`, and
`.github/workflows/forecast-audit-ui.yml` for exact new path filters, syntax
checks and native Node24 test setup only. Root may add one separate focused
integration test with saved fixtures after author implementation. No existing
model, odds worker, original root asset or other workflow is in write scope.
