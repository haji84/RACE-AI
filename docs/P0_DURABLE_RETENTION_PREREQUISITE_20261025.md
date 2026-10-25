# Race33 Goal/Done: private retention before public intent

Add an explicit local retained-submission profile to the original attempt
owner. Original whole typed wire remains in the immutable case; no second
model journal, odds upsert, expiring reservation, new transport or service.
Do not migrate/retrofit old stores or change legacy hashes/ACKs. Original held33
and all old source/run/nonce stops remain untouched. Device/cost acceptance is
later; real source, external storage, shared global coordination, security,
deployment, main and98% remain distinct unmet gates.

Independent criticism: artifacts/race33-design-criticism.md,
SHA987545684bc285a6228de43800598c09168e3146a6695e533d281777d5d9096e.
This additive local code needs no new Owner confirmation. Actual external
resource/rights/security/paid/public/main decisions keep their existing Gates.

## Fixed public API

New module `race_ai.retained_case_submission` provides only these prospective
entry points, with no default writer or source/owner/store authority:

```
reserve_retained_case(attempt_path, case_path, *, expected_request_sha256,
    expected_branch, submission_source_sha40, slot, assignment_ref,
    destination, retention_policy, clock, private_path_verifier=None,
    admit_store=None)
admit_case_retention(attempt_path, case_path, *, expected_request_sha256,
    expected_reservation_sha256, readback_bytes, readback_descriptor,
    receipt_claims, receipt_proof, clock, private_path_verifier=None,
    admit_store=None, admit_source_storage=None, admit_owner_destination=None,
    admit_coordinator=None, admit_protected_readback=None,
    verify_independent_receipt=None)
dispatch_retained_case(attempt_path, case_path, *, expected_request_sha256,
    expected_reservation_sha256, expected_branch, submission_source_sha40,
    clock, private_path_verifier=None, admit_store=None, verify_source=None,
    verify_cutoff=None, admit_model_roster=None, independent_release_check=None,
    admit_transport=None, admit_retention_action=None, transport=None)
```

Extend existing GET-only `recover_submission_attempts` with explicit keyword
`submission_contract="LEGACY_V1"` and `expected_reservation_sha256=None`.
New recovery requires `submission_contract="RETAINED_V2"` plus the exact C SHA.
No automatic header-based fallback. An internal fixed selector may also be
added to existing dispatch so the wrapper reuses its exact writer/core; it is
not an arbitrary plugin/callback registry. Default legacy API/result/domain/
SQLite schema and existing saved case/ACK bytes remain exact.

Return reservation SHA, complete reservation C and existing base B after
successful reserve; return C/R/E identities after admission. Callers do not
supply R or a supposedly ADMITTED report. Admission reconstructs R internally
through existing retention APIs. New action callback signature is
`admit_retention_action(claim, prerequisite)`; fresh bounded copies bind complete
C/R/E identities, exact public target/model/phase, cutoff and retention horizon.
It must admit the actual full capability through those windows, not echo flags.
Missing/nontrue/mutating callbacks fail closed. Return scopes stay explicitly
LOCAL_CONTRACT_CALLBACK_ATTESTED, with authenticated rights/producer/time/cloud/
global/cloned-store/official/scoring stronger flags false.

## Identity and acyclic graph

Slot exact schema `RACE_AI_PROSPECTIVE_COMPARISON_SLOT_V1` and fields:
schema, scope_ref, race_id, race_revision, as_of_utc, model_ids. Use canonical
source race ID, positive original revision, normalized original UTC as_of and
ordered original four model IDs. No nonce/case_id/wire hash/pin/version/first
intent in logical slot key. Those are immutable bound values; changed values
under the same slot stop in the same store. Legitimately new snapshots/scopes
require a separately predeclared assignment, not an automatic retry path.

Store admission binds ENTIRE slot, actual sole path/assignment, case/pin/plans,
destination/cap/horizon/policies, executor and repository/audit branch. A bare
scope_ref is insufficient. No arbitrary fresh path self-certifies uniqueness;
same-host cooperative assignment is callback-qualified, not a global registry.

B is existing PRE_PUBLIC_BASE_ONLY, binding original case/wire/ordered plans/
destination and fixed versioned coordinator contract plus independently admitted
assignment identity. B MUST NOT contain C's final SHA. C binds full slot/assignment,
base public manifest/case/model pin/settings/target and complete B. R binds B;
E binds C, reconstructed R, original whole-wire identity, protected readback,
independent receipt/proof and exact recorded callback decisions. M binds C/R/E
and original case. Intents bind M. No C/B cycle, per-model wire rewrite or second
retention operation. Identical concurrent reservations may both return the same
single C; divergent C values under the same store stop.

### Reviewed correction: preserve the final local highwater across restart

The first implementation's C/E timestamps described proposal creation before
slow admission callbacks, while its last observed clock was checked but not
stored. That permits an older receipt to pass the proposal lower bound and
loses the final highwater on restart. Preserve that original P2/RED separately.

Keep the already admitted inner C identity and existing acyclic B/R unchanged.
Store C and E in exact, bounded immutable row envelopes with separate versioned
row digests. The C envelope binds exact C and its final `commit_guard_at`;
E binds that C-row identity/guard and has its own final guard. M and action
prerequisites bind both final row identities/guards. After all arbitrary
path/store callbacks and lock acquisition, sample/check the final guard,
seal its envelope and perform only SQLite INSERT/COMMIT and cleanup. Do not
discard a later observed guard or mutate C after its full identity admission.

The guard is a local precommit observation/lower bound. It does not authenticate
physical COMMIT completion, independent UTC or external receipt time. No new
table, registry, backend, authority, writer or Owner gate is introduced.
Cached reads validate the recorded guards/digests without clock renewal.

## One store and irreversible action boundaries

Explicit new store version2 has original three tables/triggers plus immutable
single C and E rows. C alone and C+E before public M are valid phases. Keep
application_id and exact fixed table/trigger sets per selected version. Reject
foreign, crossed or rehashed inconsistent stores without DDL/migration. Bound
metadata/proof at64KiB each (opaque proof BLOB), original wire4MiB, all original
typed bytes/hashes/order. Do not duplicate the wire in attemptDB. Preflight
SQLite typeof/byte lengths under one read snapshot before variable fetch.

Reserve under BEGIN IMMEDIATE/FULL with original load_case and private/store
admission. Admission reconstructs original Race29 handoff using fresh source
private-storage, owner/destination/horizon/cap and coordinator gates, then the
existing whole-wire/protected-reader/independent-receipt verifier. Never use a
caller report as a capability. Persist exact bounded R/descriptor/claims/proof
and callback-qualified evidence in E. E must COMMIT in a PRIOR transaction
before any public intent. Reserve/admit do not call an external private-retention
writer. Dispatch uses the existing separately admitted public writer below.

Required chronology: case persisted <= C reserved <= C-row final guard <=
receipt committed <= protected readback observed <= E admitted <= E-row final
guard < official cutoff; every public intent/restart highwater is at least the
E-row guard. The verification observation also precedes E admission. retained_until
covers the declared horizon beyond cutoff. Fresh highwater UTC and all gates
must hold after slow callbacks/lock and immediately precommit. Analysis-window
admission through cutoff does not itself grant long-term retention rights.

Replay C/E uses recorded semantic evidence and exact supplied expected case/C
and immutable claim/proof/readback identities; no inference, fabricated True
callbacks, authority renewal or clock requirement for an identical cache.
Private/store read checks remain. Factoring existing pure retention validators
is allowed if public V1 outputs/exceptions stay exact. No duplicated ~200-line
retention verifier, public writer or recovery state machine.

Fresh dispatch semantically validates C/R/E against the original case in the
SAME store transaction, rechecks existing exact-action gates plus new retention
gate at PRE_INTENT/PRE_PUT, then commits consumed intent before PUT. Unknown
write/readback keeps its permanent barrier; only actual normal writer return
creates ACK. A PRE_PUT denial after consumption intentionally leaves a barrier,
even with0PUT. Cached ACKs/recovery do not clear it. Known-commit recovery stays
bounded GET-only and cannot create ACK or resend. No expire/reclaim/reset path.

## Done evidence and work ownership

TDD actual fixed case -> reconstructed R -> whole-wire/receipt verifier -> durable
E -> existing fictional writer/recovery. Missing/advisory/partial/copied/wrong-
case/destination/evidence must yield0intent/0PUT before consumption. Rehashed
semantic/header/type/length refusals, source/retention/action gate mutation,
cutoff/rollback after callbacks and commits, original legacy byte/ACK fixture,
two real local processes sharing one store, crashes before/after C/E/intent
COMMIT and restart/barrier/no-retry behavior. Preserve all original predictions
and denominators; no new real forecast, result or performance claim from fiction.

C owns existing submission core, new retained helper and focused tests; it may
minimally extract pure validators in private_wire_retention with unchanged V1
regression. Root owns integration tests/CLI/workflow/docs/Git and serializes
existing Draft PR72 writes. D is nonauthor reviewer; A audits bytes/inputs.
Final parent tests, exact-head hosted CI, independent review and packet audit
are separate evidence. Source/backend/deployment/real E2E remains unproven.
