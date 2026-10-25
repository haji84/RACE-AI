# Durable submission intent for an original prepared case

## Goal and existing assets

Base72b8c94d8a4b590e426d4909ce33621a86493090 closed the previous unit:
441 exact-head hosted tests, separate technical reviews, one retained-real-input
NO_FORECAST and an independently audited169-payload packet. These do not prove
real prospective E2E. Device/cost acceptance remains deferred by the owner.

Implement the documented next dependency: consume a durable per-model intent
before invoking the existing create-only fingerprint writer, retain a concrete
PUT commit before its readback, and make uncertainty irreversibly read-only.
Reuse permissioned_model_case.load_case, the fixed ordered four original plans,
append_only_freeze_writer.submit_anchor and github_witness_resolution. Do not
change the immutable case DB, original model/pin, old synthetic journal, held33,
default writer or remote storage. This unit performs no actual submission.

Independent design criticism is recorded privately in
race28-submission-attempt-design-review.md, SHA256
a6d946edb3216c5c772475e52c177ddd56196123c6ef9f175fb7d0b5f18a4c50.
Changing the case DB was rejected because its exact identity is immutable.
A separate local one-case attempt DB is the smallest chosen component; an
external shared CAS/storage service is a separate authority and deployment task.

## Manifest and capabilities

Both APIs load the actual committed case by its independently supplied request
SHA. Bind its request/wire/delivery hashes, ordered four IDs/versions/model pin,
exact plan paths/canonical anchor hashes, executor contract and fixed repository
haji84/RACE-AI plus one admitted audit/freeze-* branch in an immutable manifest.
Never accept replacement predictions, a model subset, a new nonce, reset flag
or arbitrary writer receipt. Foreign DBs must remain unchanged.

All private-path, exact store identity, input/source-purpose, current official
cutoff, original model roster, public-fingerprint release and audited transport
capabilities default to denial. Their exact-True verdicts bind the original
manifest/model/destination; copied callback arguments cannot retarget it. Store
admission must identify the one approved physical/persistent state, not simply
assert that any new path is safe. Real OS ACL checks remain independently
implemented; reuse the reviewed no-follow path checks rather than duplicating
their prior UNC/reparse/hardlink errors. No credential, raw source, complete
HTTP response or private exception text belongs in the attempt DB or summaries.

An explicit bounded transport is required. Never fall through to urlopen.
Fresh per-model checks and an aware, nondecreasing clock are rechecked after
lock waits, slow callbacks and immediately before PUT. Closed cases may only
replay/recover; historical preparation grants no new public-release permission.

Each exact-action True verdict must authorize the original action through the
manifest's sales_cutoff_at, not merely at the callback's sampled instant. A
source/release grant expiring before that cutoff must deny even while it is
temporarily valid. Store/roster/transport admission has the same required window.
This is the trusted capability contract, not proof of expiry from a Boolean;
the library's stronger authentication flags remain false. Test an honest
expiry-aware gate and a slow final gate crossing cutoff explicitly.

## Transaction and stop contract

Use exact SQLite schema/application identity, atomic initialization, FULL
synchronous and BEGIN IMMEDIATE. One immutable case manifest, at most four
immutable consumed intents and narrowly typed append-only evidence suffice.
Bound every variable-width field before materialization; reject malformed
types, UTF-8, hashes and private parsing errors safely. Do not implement a
general scheduler, generalized event journal or another prediction algorithm.

Each claim checks the fixed next model and all previous intents under the same
write transaction. COMMIT the consumed intent before invoking the legacy writer.
An uncertain local COMMIT must cause zero writer calls. No intent is deleted,
updated, recreated or retried. A guarded request permits at most one original
create-only PUT and its exact-commit GET. Validate original canonical body,
destination, order and counts, with sticky failures even if callbacks swallow
an exception. Persist the strict returned commit SHA before handing the PUT
response back to the legacy writer, so a later GET failure retains that commit.

Only the original invocation's validated normal legacy return can append its
normal completion ACK. Any intent without that ACK blocks dispatch of every
remaining model, including while the original process is still working.
Recovery may append a verified witness but cannot invent the ACK or clear the
barrier. No lease, timeout, age, repeated404 or new nonce grants another PUT.
Successful earlier models remain distinct from unattempted later models.

Normal ACK means only the legacy create-and-pinned-readback completed. It is
not an external timing receipt. Do not couple immediate normal dispatch to a
workflow-run becoming visible; witness resolution is a separate read-only API.
Committed normal results replay without writes. After normal ACKs a later
invocation may continue only unattempted models, through every fresh gate,
before cutoff. A failed/crashed unACKed intent remains permanently read-only.

## Read-only recovery and evidence limits

Recover only the captured exact commit; unknown commit yields STOPPED/zero
reader calls. Do not scan a branch, accept a hint/foreign receipt or write a new
path. Reuse the existing fixed3GET resolver unchanged and retain its separate
observation time. Cached verified evidence can be returned without re-query.
No timers, automatic polling, dispatch, provider fetch or model rerun are added.

Report all four models, including NOT_ATTEMPTED and unresolved intents. Local
intent, normal ACK and external fingerprint presence are separate states.
The summary's github_reads counts guarded GET invocations in that API call,
including failures; dispatch replay and cached recovery report zero. This
does not measure internal transport retries or actual server request counts.
Source rights, authentic producer execution, complete eligible denominator,
formal scores and whole private-payload cloud retention are not conferred.

This component offers bounded guarded invocation in one cooperatively shared
physical DB. It cannot authenticate cloned/restored stores, stop an untrusted
transport retrying internally, prove global exactly-once delivery or establish
continuity across GitHub runners. Require independent store admission and keep
those stronger claims false. Protected external full-payload retention, genuine
future real input/result E2E, formal review/main and forward98% remain unmet.

## Verification and scope

Use a small original fictional prepared case with the actual pinned codec and
models once, then recording transports. Test real subprocess crashes around
intent COMMIT, PUT/capture, GET and ACK; real concurrent claimants/case-wide
barrier; unknown commit zero reads; known read-only recovery never clears the
barrier; fresh authority/deadline/rollback checks; immutable/foreign/corrupt/
oversized store; callback mutation/guard swallowing; private traceback leakage;
all-four status and explicit cloned-store limitations. No real source or
GitHub submission is needed for these tests.

Run relevant regression, exact-head existing hosted CI, nonauthor technical
review, new-unit byte backup/restore audit and Issue68 closeout. No new paid
service, source-purpose expansion, cloud/Access/credential change, schedule,
public deployment, main merge, betting or held33 retry is authorized here.
