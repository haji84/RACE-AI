# Retained training validation: local performance evidence

PR63 reuses the registry keys already bound within one `verify_training` call.
Every row, source, hash, clock, rights and retirement check still runs. Direct
generation verification obtains a fresh registry on every call. No success memo,
new model, weights, job or permissions are introduced.

The reviewed runtime change is `469e06cd332a6e3553ea2578d39cb4f87e386eac`.
Original PR63 head `eee30c0a` remains an ancestor, without applying its old Blob
SDK tree. The exact prepared code-only tree is recorded separately from these
evidence documents in [the count/hash proof](evidence/boat-registry-validation-profile-20261117.json).

The authored fixture contains 30 fitted cells, a 1,076,946-byte training body,
240 generation rows and 88 source closures. Six pair/PDCA partitions and the
complete training context pass actual AES readers using fixture keys.

| Profiled phase | M2 seconds | Candidate seconds |
| --- | ---: | ---: |
| Make six AES pairs | 14.409 | 6.851 |
| Admit six AES pairs | 8.087 | 4.011 |
| Score six AES pairs | 30.407 | 15.212 |
| Retain six AES pairs | 8.861 | 3.614 |

Validation/native/source-check counts are identical. Six canonical forecasts,
PDCA verdicts and the public creation summary are byte/value equivalent.
135 regression tests, 25 final-location/workflow tests and 25 integration tests
passed. Independent review passed 35 tests, 14 resealed mutation/subclass probes,
fresh policy checks and six exact forecast comparisons.

Timings include cProfile overhead and apply only to this synthetic fixture.
The live worker's 20-minute rounds, T15-to-T10 deadlines, all-day coverage and
prospective accuracy remain unproved. Current M2 code and its single running
worker are unchanged; this candidate requires its own normal CI and release.

The final candidate also preserves exact M2 `86b029ae` checkpoint/control
readback for a future release. Tests replay both old origins with unchanged
counters; an old checkout or old proof still cannot authorize that release.
The new M2 case reproduced `ORPHAN_SOURCE_NOT_REVIEWED` before the literal
read-only origin addition. Sixty related tests and 68 independent tests passed.

Existing RESULT-retention tests exposed the earlier batch publisher's stricter
independent-reader contract: two legacy fixtures lacked an explicit separate
reader. The test-only repair separates writer-local objects, published remote
objects and the reader snapshot, asserts full archive/metadata/manifest bytes
on first and repeated reads, and refuses unpublished or corrupted bytes.
Retention/vault/batch runtime is unchanged. Seven target and 57 related tests,
plus 55 independent tests and two extra probes, passed. The existing source CI
job now includes that test module; no job or permissions were added.

These additions require CI on the final combined head. Earlier CI success on
the performance-only revision is retained as history, not reused as approval.
