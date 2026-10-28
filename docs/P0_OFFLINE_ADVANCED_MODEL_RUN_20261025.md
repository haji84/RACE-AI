# Offline advanced model run implementation plan

Goal: resume an authored eight-race, four-sport synthetic run through existing
PR71 delivery/transport and PR72 binding, prepared anchors and settlement.
This is additive local SQLite orchestration, not an external freeze or a real
source execution permission. The approved execution method is inline TDD;
parent owns independent review, CLI, workflow, commits and integration.

Only `race_ai/offline_model_run.py`, `tests/test_offline_model_run.py` and this
document are in the implementer's scope. PR69 `SyntheticJournal` is unchanged.
Model dependency pin: `ebe93f13062cf0461b81b924a5dc0482ada37b56`. Unchanged
settlement contract base: `2a99473c4755932e2d395b9e785be4f4835aef99`.
The new runner's actual commit is recorded later by the parent; these pins do
not authenticate execution or supply prospective external model admission.

API:

```python
SyntheticModelJournal(path, *, clock, codec, validate_snapshot, allow_source)
journal.run(manifest, *, delivery_factory)  # eight job summaries
journal.add_results(claims)                # immutable normalized revisions
journal.report(*, synthetic_gates=None)    # classified settlement wrapper
journal.close()
```

The factory signature is `factory(job, *, at)` and returns the unchanged
`deliver(raw, policy, at=at, persist=False)` dictionary. `codec` is the pinned
module's existing serialize/deserialize API. Constructor callbacks are explicit
trust interfaces, not rights authentication. Only the parent's authored fixture
CLI may inject synthetic settlement gates: roster, results, cutoff and coverage.
The runner always supplies `freezes=[]` and never creates external receipts.

Manifest: exact schema `RACE_AI_SYNTHETIC_ADVANCED_RUN_V1`, scope
`SYNTHETIC_ONLY`, aware `planned_as_of`, the two source pins, fixed four IDs and
their `0.1.0-UNTRAINED` versions, unchanged discovery `ledger`, and `jobs`.
Exactly eight canonical ledger identities contain two races per model sport;
horse source IDs retain their explicit JRA/local alias. Jobs match the complete
ledger once each. Each job has `race_id` and `input_check`: either null, or exact
`as_of`, `source_payload_sha256`, `policy_record_sha256`, and
`feature_snapshot_sha256`. Cutoff is owned by ledger `sales_cutoff_at`.
Finite canonical copies prevent caller/factory mutation. The manifest hash has
its own schema domain and is immutable for one database.

Two tables hold append-only advanced events and a mutable clock high-water.
Events bind sequence/key/kind/recorded_at/canonical metadata/content SHA/previous
hash. DELIVERY content is exact transport bytes. MANIFEST, DELIVERY,
NO_FORECAST, RESULT and EVALUATION are the only kinds. DELIVERY and NO_FORECAST
share `job:{race_id}`, preventing replacement. UPDATE/DELETE triggers and FULL
synchronous transactions preserve local append-only behavior; this is not a
trusted clock or external storage witness.

- [x] Write behavioral tests and capture missing-module RED in ignored artifacts.
- [x] Implement manifest admission, canonical copying and semantic journal replay.
- [x] Hold BEGIN IMMEDIATE across prior-job lookup, local factory, codec,
  existing binding/model validation, four prepared anchors and commit.
  Sample clock before computation and immediately before commit. Unexpected
  failures roll back and propagate. Committed replay precedes cutoff checks.
- [x] Append consecutive result claims and canonical evaluations; report all
  eight races even after partial execution. Default authority remains denied.
- [x] Exercise real subprocess termination before/after commit and concurrent
  identical execution, corruption, revisions, cutoff crossing and clock rollback.
- [x] Capture focused GREEN; parent performs full CI and independent review.

Review focus: changed/rehashed but wrong input wire; omitted model; rehashed
journal chronology; mutation inside callbacks; process loss at transaction
boundaries. Reopen/report replay semantic checks under one SQLite snapshot,
including unchanged model hashes, complete prepared plans and all revisions.

No network/provider/cloud calls, new dependencies, real input planning,
learned coefficients, default writer changes, receipts, wagers or public output.
Crash during an uncommitted computation may cause recomputation. Serialization
and committed replay prevent concurrent duplicate inference and recomputation
after commit, not exactly-once model execution.

## Implemented contract and evidence

`run` orders by parsed ledger cutoff then race ID, retaining unknown cutoffs at
the end. Its summaries remain in original ledger order. Each summary has
`race_id`, `state` (NOT_RUN, DELIVERY, NO_FORECAST), `reason`,
`delivery_sha256`, `prepared_anchor_count`, `generated_at`, and `persisted_at`.
Absent values are null and absent plans count zero. A DELIVERY requires all
four declared models; settlement's allowance for missing model forecasts does
not permit a partial DELIVERY bundle.

`report` returns `schema`, `scope`, `manifest_sha256`, `basis_sha256`, `jobs`,
`prepared_anchor_count`, `simulation_gates_used`, `external_time_attested`,
`official_prediction`, unchanged `settlement`, and its own `evaluation_sha256`.
The basis hashes all input events, excluding earlier evaluations, so unchanged
reports are idempotent. Simulated gates are limited to `admit_model_roster`,
`verify_result`, `verify_cutoff`, and `verify_coverage`. There is no freeze gate.
Default formal metrics remain null. Explicit fixture gates can demonstrate an
eight-race denominator and zero captured freezes despite 16 prepared anchors.

The journal captures exact Boolean source-analysis verdicts and complete
synthetic settlement verdict maps. Their keys bind canonical callback arguments;
values and the entire maps are event-hashed. Replay uses recorded decisions,
not renewed authority callbacks. The pinned codec and structural snapshot
validator still execute. Recorded fictional admission is not a fresh rights
decision, independently authenticated source claim or external timing witness.
Replayed deliveries bind original input/policy/snapshot hashes and `as_of`,
ingestion/start/generation/persistence chronology, full original four-model
output, and every unchanged prepared anchor. Evaluations are recomputed from
their original input basis and captured verdicts. All reads occur under one
SQLite transaction snapshot.

Clock high-water checks occur before work and immediately before COMMIT,
including after the DELIVERY row is inserted. A deadline crossed after insertion
rolls back the bundle. The recorded local persistence sample does not establish
actual external commit time. Original committed timestamps and bytes survive
post-cutoff retries. Result claims must be consecutive, confirmed no later than
recording, and cannot predate an existing delivery or a final-result cutoff.

Validation used the owner's Python 3.12 venv with `-B -X utf8`:

- `artifacts/race26-runner-author-red.txt`: 19 expected assertion failures for
  the absent production module, before implementation.
- `artifacts/race26-runner-author-green-initial.txt`: historical initial run;
  three subprocess import-path failures and five Windows temporary-file cleanup
  errors were test-harness issues. Explicitly closed SQLite reader connections
  and an explicit worker import path corrected them; evidence is retained.
- `artifacts/race26-runner-author-replay-red.txt`: two expected failures for
  source-authority re-query and a rehashed start before the prior committed event.
- `artifacts/race26-runner-author-commit-guard-red.txt`: expected failure for a
  deadline crossed after insertion but before COMMIT.
- `artifacts/race26-runner-author-replay-commit-green.txt`: five targeted PASS.
- `artifacts/race26-runner-author-focused.txt`: 22 focused tests PASS in 80.790s,
  including actual authored boat6/keirin7/autorace8/horse18 model calls, 16
  original model forecasts, all eight denominator rows, process crashes and
  simultaneous processes, revisions, tampering, and no network.

The initial implementation was 417 lines rather than the approximate 300-line
target because semantic replay and recorded verdict validation remain explicit.
No backup API, leases, generic scheduler, real-input planner, external writer or
default CLI change was added. Independent review, parent CLI verification and
full CI remain separate acceptance steps. Synthetic success is not evidence of
real source rights, external freeze compatibility, prospective accuracy or
production operation.

## Independent review repairs

Independent D identified three material gaps. Each was reproduced before its
repair; earlier 22-test author and 375-test parent results are historical and
do not constitute verification of these later changes.

1. Python loose equality allowed an idempotent retry to bypass the existing
   strict result parser (`revision_no=True/1.0`, integer offered flag, floating
   payout), and accepted a rehashed report/plan with numeric zero replacing
   false. Duplicate claims now pass the existing parser in their original
   revision context and compare finite canonical JSON. Manifest, plan, report
   and recorded-verdict equality also compares canonical JSON, retaining the
   distinction among Boolean, integer and floating values.
2. CREATE IF NOT EXISTS could alter an unrelated database. Constructor admission
   now holds BEGIN IMMEDIATE while recognizing the exact owned schema plus
   application ID `0x52414941` and user version 1. Only an empty zero-identity
   database may be initialized. Target DDL executes individually in the same
   transaction; executescript is used only on an isolated in-memory schema
   template. Foreign databases and changed identities are rejected before any
   target schema write, without implicit migration or trigger repair. A real
   foreign-file test compares both original bytes and original schema. Tests
   that forge event hashes restore the original trigger before reopening so
   schema rejection does not make semantic-tamper checks vacuous.
3. All-missing jobs could bypass race-day consistency. Every manifest now
   requires an ISO canonical event date and every known cutoff's JST date must
   match it, including when no model will run. Equivalent aware timezones remain
   accepted. A missing cutoff remains an explicit CUTOFF_UNKNOWN job when input
   is supplied, and all eight rows remain in the report.

Preserved review evidence:

- `artifacts/race26-runner-author-d2-red.txt`: four tests, seven expected failing
  subcases reproducing typed equality and foreign-database mutation.
- `artifacts/race26-runner-author-d2-calendar-red.txt`: three tests, three
  expected failing subcases for identity and calendar admission; equivalent
  timezone/unknown cutoff behavior already passed.
- `artifacts/race26-runner-author-d2-green.txt`: nine targeted tests PASS in
  5.360s, including concurrent first-open and a nonvacuous rehashed transport.
- `artifacts/race26-runner-author-post-d2-focused.txt`: all 29 focused tests
  PASS in 81.636s on the required Python 3.12 venv. The repaired production
  module is 457 lines. Parent full CI and D's independent execution/re-review
  remain separate acceptance evidence.

No performance optimization or timeout increase accompanied these repairs.
