# Race35 Goal/Done: one consumed private-retention action

2026-10-26 JST. Prospective local-only addition to the SAME existing attempt
owner at PR72 baseline `8c813eedab0cc534a0f1388dfde147761a88d155`.
The baseline was clean before these two design documents were written.
Independent design input: PR71 ignored `artifacts/race35-design-criticism.md`,
SHA256 `7b292ab928b027b5d9ca699e3978e50d2b4fe2384743f8368ad001dab990e387`.
This exact freeze needs D criticism and root implementation authorization
before product/test changes. No implementation approval is implied here.

## Goal, Done and limits

For a newly assigned PRIVATE_ACTION_V3 comparison slot, reconstruct the
original whole-wire retention request R from an actual case and committed C,
commit one immutable private-create intent P in the existing attempt SQLite
store, then allow only that invocation's normally returned P COMMIT to make
one explicitly admitted exact local create call. Any existing P is consumed,
including crash/denial before the destination and zero actual writes. An
uncertain destination commit permits exact read recovery only.

Done includes real process concurrency/crashes, semantic replay and unchanged
V1/V2 behavior/bytes, plus a test-only original-wire integration through the
ACTUAL pinned Race34 vault/native SQLite. It does not add a private ACK table,
second coordinator/model journal, production Node bridge, HTTP service,
receipt issuer, backend registry, cloud resource, model run or automatic
private-to-public release. Local readback remains RETENTION_UNVERIFIED;
missing genuinely admitted protected-reader/independent-receipt capability
means E absent and public intents/PUT0.

## Fixed production APIs

New `race_ai.private_retention_action` exports exactly these operations:

```python
consume_private_retention_action(attempt_path, case_path, *,
    expected_request_sha256, expected_reservation_sha256, expected_branch,
    submission_source_sha40, private_adapter_declaration=None, clock=None,
    private_path_verifier=None, admit_store=None, admit_source_storage=None,
    admit_owner_destination=None, admit_coordinator=None, verify_cutoff=None,
    admit_model_roster=None, admit_private_action=None,
    admit_private_adapter=None, private_create=None)

read_private_retention_action(attempt_path, case_path, *,
    expected_request_sha256, expected_reservation_sha256,
    expected_private_action_sha256, clock, private_path_verifier=None,
    admit_store=None, admit_private_reader=None, private_read=None)
```

`expected_private_action_sha256` always means the FINAL P ROW digest. It is
not the P candidate digest. No caller R, vault claim, locator, report, new
nonce, alternate target or reusable write permit is accepted. Inputs and
callback arguments are finite bounded owned copies; original `bytes` wire
and forecast data are never changed. Missing/nontrue/mutating admissions deny.

Existing retained reserve/admit/dispatch gain the fixed keyword
`submission_contract="RETAINED_V2"`; admit/dispatch also gain
`expected_private_action_sha256=None`. For PRIVATE_ACTION_V3, fresh E and
public dispatch REQUIRE the exact final P hash. Core GET-only public witness
recovery adds the same expected-P keyword and accepts explicit
`submission_contract="PRIVATE_ACTION_V3"`. Its default stays LEGACY_V1.
No header inference, fallback, new model-case profile or migration is allowed.

## Fixed profiles, SQL and domains

LEGACY_V1/user_version1 and RETAINED_V2/user_version2 remain exact: defaults,
fieldsets, domains, SQL, saved case/attempt/ACK bytes, clocks and replay
behavior. Original model-case V1/V2 source pins and typed wire stay unchanged.
Use fixed internal profile parameters, never caller configuration dictionaries,
module-global switching, import-path swaps or a copied C/E state machine.

PRIVATE_ACTION_V3 uses application_id `0x52415355`, user_version3, exactly
the original three tables/triggers and C/E tables/triggers, plus:

```sql
CREATE TABLE submission_private_action(
    id INTEGER PRIMARY KEY CHECK(id=1),json TEXT NOT NULL,sha256 TEXT NOT NULL)
```

Its BEFORE UPDATE and BEFORE DELETE triggers use the existing
`immutable submission` ABORT behavior. A BEFORE INSERT trigger rejects
EXISTS(id=NEW.id), including REPLACE. There is no update/reset/expiry/reclaim,
private ACK, private recovery-history table, wire BLOB or per-model P.
New stores only: refuse all foreign/crossed/partial schemas unchanged; never
adopt or modify old stores. Full-slot external assignment must independently
deny parallel/retry assignment of the same stopped logical comparison.
The library cannot authenticate global uniqueness or prevent cloned DBs.
Valid phases are C-only (P/E/M/public absent), C+P (E/M/public absent),
C+P+E (public optional), then original public intents/evidence. C-only replay
may lack P; every present P is validated, and E/M/public rows require P.

New V3 schema literals:

| Identity | Literal |
| --- | --- |
| C | RACE_AI_RETAINED_SUBMISSION_RESERVATION_V3 |
| C row | RACE_AI_RETAINED_RESERVATION_ROW_V3 |
| E | RACE_AI_RETAINED_SUBMISSION_ADMISSION_V3 |
| E row | RACE_AI_RETAINED_ADMISSION_ROW_V3 |
| M | RACE_AI_PERMISSIONED_SUBMISSION_MANIFEST_V3 |
| public claim/result | RACE_AI_PERMISSIONED_SUBMISSION_CLAIM_V3 / RACE_AI_PERMISSIONED_SUBMISSION_RESULT_V3 |
| retained prerequisite | RACE_AI_RETAINED_SUBMISSION_ACTION_PREREQUISITE_V3 |
| P candidate | RACE_AI_PRIVATE_RETENTION_ACTION_V3 |
| P row | RACE_AI_PRIVATE_RETENTION_ACTION_ROW_V3 |
| private gate claim/result | RACE_AI_PRIVATE_RETENTION_ACTION_CLAIM_V3 / RACE_AI_PRIVATE_RETENTION_ACTION_RESULT_V3 |

Retained-style hash H(domain,value) is SHA256(domain ASCII + NUL + canonical
finite UTF8 JSON), using existing retention canonical semantics. C/C-row/E/
E-row/P-candidate/P-row use their exact schema literal as domain. Public
MANIFEST/INTENT/EVIDENCE use the current core's domain algorithm with V3:
`RACE_AI_PERMISSIONED_SUBMISSION_<KIND>_V3` + NUL + canonical JSON.
No old digest is rewritten. V3's fixed coordinator contract SHA is
SHA256(ASCII `RACE_AI_RETAINED_V3_PRE_PUBLIC_FULL_SLOT_PRIVATE_ACTION_V1`),
binding the same cycle-free PRE_PUBLIC_BASE_ONLY B shape. R29 R and Race34
claim/locator schemas and algorithms remain unchanged.

## Exact adapter declaration and actual original claim

The supplied declaration must equal this complete fixed plain dictionary:

```json
{
  "schema":"RACE_AI_PRIVATE_RETENTION_LOCAL_ADAPTER_V1",
  "destination_contract":"LOCAL_SQLITE_D1_BATCH_CANDIDATE_V1",
  "runtime_scope":"EXPLICIT_INJECTED_LOCAL_TEST_CANDIDATE_ONLY",
  "source_commit_sha40":"9aeb2b425de9d05a44cb31f72a242a5111ada80a",
  "vault_module_sha256":"383264d3a676e04fc91a6c4956ef79d5bda709a09f6ad5b03e0d6062b6891024",
  "vault_schema_sha256":"950646a723ba6b6fed4446084a9f1510fb18b1540dcc0c5c5ff1cba0eae41b0c",
  "native_test_adapter_sha256":"04c26b80e27110b891e297a0d615cf99e9db84446f4d1ee978274f64f88db215"
}
```

For V3 C, destination.adapter_contract_sha256 must equal
H(RACE_AI_PRIVATE_RETENTION_LOCAL_ADAPTER_V1,declaration). It must declare
the frozen local-private-vault- destination grammar and original cap/horizon.
These declarations do not authenticate runtime execution. Original
model_source_sha40 comes from the case, distinct from submission executor,
Race34 code commit and test bridge. Never substitute the Race34 commit for
an original model source pin.

Derive the complete unchanged Race34 claim from the ACTUAL loaded case+C/R:
request_sha256=original case request; wire_sha256/delivery_sha256; original
model_source_sha40; destination_ref unchanged; owner_ref=owner_scope_ref
unchanged; R/C/C-row SHA and exact C-row UTC guard; exact retain_until;
protection_policy LOCAL_INSERT_ONLY_SQL_V1; original wire count and ordered
512KiB chunk SHAs. Its schema/contract and <=8KiB canonical bound are Race34's.
No JSON decoding/re-encoding or model execution. Compute its frozen locator
SHA256(UTF8 `RACE_AI_LOCAL_PRIVATE_WIRE_LOCATOR_V1` + NUL + sorted canonical
claim JSON); compare exact bytes/scalars/order. Preserve original UTC strings
and microseconds, never truncate to JavaScript milliseconds.

## Exact P candidate and row

P candidate has ONLY these fields:

- schema, submission_contract=PRIVATE_ACTION_V3,
  action_kind=CREATE_LOCAL_PRIVATE_WHOLE_WIRE, phase=PRE_PRIVATE_INTENT;
- case_request_sha256, reservation_sha256, reservation_row_sha256,
  reservation_commit_guard_at, retention_request_sha256;
- vault_claim, vault_locator, private_adapter_declaration;
- candidate_at (normalized aware UTC sample, >=C guard and <cutoff);
- window exactly `{through_cutoff_at,retain_until,purposes}` using the actual
  original cutoff/horizon and ordered analysis/private_storage/private_derived.

Candidate SHA is H(RACE_AI_PRIVATE_RETENTION_ACTION_V3,candidate). It is a
proposal, not an admission record or permission. PRE_PRIVATE_INTENT gates
cannot bind the unknown final row SHA/guard and receive null for those values.
Do not modify the admitted candidate after a slow gate.

Final row JSON is exactly:

```text
{schema:RACE_AI_PRIVATE_RETENTION_ACTION_ROW_V3, action:P_candidate,
 admissions:{source_storage:true,owner_destination:true,coordinator:true,
 cutoff:true,roster:true,private_action:true,private_adapter:true,
 path:true,store:true}, commit_guard_at:final_UTC_sample}
```

These are actual recorded exact-True PRE_PRIVATE_INTENT decisions, never
fabricated True callbacks. Sample guard AFTER the final arbitrary gate/path/
store callback and lock delay, immediately before INSERT/COMMIT. Hash the
whole row with the P-row domain. Every variable SQL column is scalar
typeof/byte-length checked under the same snapshot BEFORE fetch; canonical
finite row JSON<=64KiB, SHA exact64 lowerhex. Semantic reload reconstructs
case/C-row/R/vault claim/declaration/locator/candidate and all admissions,
not only its hash. C guard<=candidate_at<=P guard<cutoff.

No final P identity flows back into B/C/R or the Race34 claim. Graph:
B excludes C-final/P/E; C/R bind B; vault claim binds C-row/R; P binds the
claim/locator; E binds P/C-row/R; M and public intents/actions bind P/E.

## Fixed callback and operation arguments

Reuse R29 callback signatures: source_storage(R,original_snapshot),
owner_destination(R), coordinator(R,B). Their True must independently attest
the exact original purposes/destination/cap/protection/retention horizon.
Old case decisions, mutable policy.grants or an analysis window do not grant
new storage authority. No public-release gate is required for private storage;
private admission never authorizes public release.

Private `action_claim` is exactly `{schema,phase,candidate,
candidate_sha256,private_action_sha256,private_action_commit_guard_at,checked_at}`.
The schema is the private-gate literal above. phase is PRE_PRIVATE_INTENT,
PRE_PRIVATE_CREATE or PRIVATE_READ_RECOVERY. The first phase has null final-row
SHA/guard; the other phases have actual committed row values. checked_at is
fresh normalized UTC.
`prerequisite` is exactly `{reservation,reservation_sha256,
reservation_row_sha256,reservation_commit_guard_at,retention_request,
retention_request_sha256,vault_claim,vault_locator,private_adapter_declaration}`.

- verify_cutoff(action_claim, original_ledger_row)
- admit_model_roster(action_claim, tuple((model_id,model_version,original_pin),...))
- admit_private_action(action_claim, prerequisite)
- admit_private_adapter(action_claim, private_adapter_declaration, private_create)
- private_path_verifier/admit_store retain current signatures; admit_store
  receives the actual path and COMPLETE C with stage keyword, never bare scope.
- private_create(owned_vault_claim, copied_original_wire_bytes): exactly one
  guarded invocation, no reusable permit, arbitrary locator/SQL/URL or fallback.
- admit_private_reader(action_claim, prerequisite, private_read) uses phase
  PRIVATE_READ_RECOVERY and actual stored row identity; no source/write renewal.
- private_read(owned_vault_claim, exact_locator): one exact read invocation.

All admission metadata is bounded copied before and after invocation and must
remain unchanged. No wire passed to admissions. The create/read seam is fixed
and default None; missing declaration/callable or any fresh required gate
denies BEFORE P. Wrapper counters count its own invocations, including throws,
not server retries, transport internals or global effects.

## Durable sequence, replay and recovery

1. Load original case and explicitly selected V3 owner without inference;
   require exact expected case/C SHA, original branch/executor and complete
   private/store assignment. Refuse existing wrong schemas unchanged.
2. If valid P already exists, return its immutable identity/consumed summary
   with0create/0read, regardless of cutoff. No source/writer/action admissions,
   clock or create function are required. An optional supplied adapter
   declaration must exactly match recorded P; None is allowed. Private/store
   access remains fresh. This is the ONLY lost-return bootstrap: reopen the
   same case/C store via consume, learn its final P SHA, then call read with
   that expected SHA. No listing/hint/new path/nonce or writer renewal.
3. Fresh P requires all source/owner/coordinator/cutoff/roster/action/adapter/
   path/store gates and a callable create seam. Reconstruct actual R using
   existing R29 admission logic and validate complete original wire identity.
   BEGIN IMMEDIATE/FULL on the SAME already-created V3 owner (mode=rw/no-create),
   semantically replay C/R/P, and check again for a concurrent P winner.
4. Recheck PRE_PRIVATE_INTENT gates and nondecreasing UTC/cutoff after lock/
   callbacks; sample final guard after the final path/store gate, INSERT P,
   COMMIT. No external writer inside a SQL transaction. A COMMIT exception or
   interrupt never invokes create, even if P actually persisted.
5. Only that invocation's normal COMMIT return owns its one call. Recheck
   source/owner/coordinator/cutoff/roster and PRE_PRIVATE_CREATE action/adapter/
   path/store gates plus immediate UTC edge<cutoff. Failure consumes P with0
   creates. No clock/window reset or postcommit rewrite. Callback internal
   retries/uncancellable delays are unproved; actual late external commit
   cannot qualify E under the cutoff chronology.
6. Invoke exact create once; validate its qualified result against original
   bytes and all fields. A normal local readback is ephemeral; P never clears.
   Binding failure, invalid return, lost acknowledgment or process death
   leaves consumed P. No retry, alternate destination, private ACK or auto-E.
7. Explicit read recovery requires exact expected final P SHA and fresh
   private/store/reader admission. Aware UTC must be nondecreasing from P
   guard and after slow reader gates; no fresh-write cutoff requirement.
   Missing/corrupt P or object is unresolved, never permission to create.
   It performs no create/schema initialization/chunk repair/source/model call,
   E write or public ACK. It does not claim to persist recovery clock history.

## Exact operation result and owner summary

The injected seam returns the frozen Race34 result dictionary exactly, with
its wire normalized to Python immutable bytes (or None for UNRESOLVED):
schema RACE_AI_LOCAL_PRIVATE_WIRE_RESULT_V1; status LOCAL_CREATED/LOCAL_READBACK
(create) or LOCAL_READBACK/UNRESOLVED (read); scope LOCAL_ONLY; locator; claim;
wire; wire_sha256; wire_bytes; chunk_count; retention_status RETENTION_UNVERIFIED;
and exactly these false fields: independent_retention_proof,
full_private_payload_retention_verified, source_rights_verified,
producer_execution_authenticated, coordinator_authenticated,
global_exactly_once_verified, cloned_store_protection_verified,
official_prediction, eligible_for_hit_at_8. Reject extra keys, aliases,
promotion, wrong type/hash/count/locator/body/claim or mutable wire.

Owner result schema is RACE_AI_PRIVATE_RETENTION_ACTION_RESULT_V3, with exact
keys: schema,status,reasons,scope,private_action_consumed,
private_action_sha256,private_action_candidate_sha256,
private_action_commit_guard_at,private_action,vault_claim,vault_locator,
create_calls,read_calls,readback, and the SAME false fields above.
scope=LOCAL_CONTRACT_CALLBACK_ATTESTED. `private_action` is the final row
envelope, `readback` is the exact validated seam result or None; absent P
identities/claim/locator are None. reasons is sorted unique fixed safe codes.
Statuses: DENIED (no P), PRIVATE_ACTION_CONSUMED_READ_ONLY (existing P or
postcommit failure/denial), LOCAL_PRIVATE_READBACK_UNVERIFIED (complete normal
local readback), PRIVATE_READ_UNRESOLVED (explicit recovery unavailable).
Counters are exact nonnegative wrapper call counts, at most1 each per API.
Malformed input/private state yields sanitized ValueError
PRIVATE_RETENTION_ACTION_REJECTED from None. Expected admission failures use
DENIED before P; after P they keep the consumed summary. Interrupts must
rollback/close any open transaction and cannot permit another writer call.
Do not expose private underlying SQL/path/body/proof/exception context in
errors/logs; never log the4MiB wire or publicize saved private fixture files.

## P before E/M/public and old invariance

V3 E, M, retained prerequisite, public claims/results and witness recovery
add `private_action_sha256` and `private_action_commit_guard_at`. E is a NEW
V3 object and must reconstruct valid same-store P BEFORE source/evidence/
receipt callbacks. An exact supplied expected P hash is required. E/M/public
rows without P, copied/rehashed mismatches or receipt-before-P deny.

Chronology retains all old verification/admission intermediate checks:
case persisted<=C final guard<=P final guard<=independent receipt committed
<=protected readback observed<=verification observed<=E admitted<=E final
guard<official cutoff. Public intent/restart highwater is at least P/E final
guards. Public gate map adds structural `private_action:true` in V3 only,
alongside existing retention/source/cutoff/roster/release/transport/store/path;
it records validated P presence, not renewed private-write permission.
Existing public exact-release gates and normal-return-only ACK are unchanged.
Local P/readback never implies genuine E, external witness or official score.

## Runtime, files and acceptance

Production Python must not import tests/support/local_private_wire_d1.mjs,
spawn a Node default, inspect secrets, choose a URL/backend or duplicate the
JS vault. The only supplied callable seam above is explicitly local/test
candidate and does not authenticate actual execution or side-effect counts.
Root owns a TEST-ONLY fixed Node bridge to actual pinned Race34 functions and
native adapter, with no listener/service and no producer. Reference bytes are
verified against commit9aeb and the hashes above, preserving model references.
Any file IPC stays outside Git, uses finite bounded input/output/error sizes,
at most4MiB binary wire plus64KiB control JSON and64KiB result metadata per
invocation, with the nested vault claim capped8KiB. stdout is a bounded8KiB
summary; stderr is discarded, never echoed. Use one30s spawn-to-reap deadline,
without reset on progress, kill then reap/join on timeout. Wire uses separate
private binary files, not command-line/base64/stdout. No automatic executable/
module/root selection: local tests use the known Node24 executable, hosted CI
uses setup-node24, with only the fixed repository helper/reference modules.
Saved originals stay ignored/local, never hosted/public fixtures.

Exact allowed paths, after D/root authorization:

- C: race_ai/permissioned_case_submission.py; race_ai/retained_case_submission.py;
  new race_ai/private_retention_action.py; new tests/test_private_retention_action.py.
- Root: scripts/verify_private_retention_action_synthetic.py;
  scripts/private_retention_action_local_vault.mjs (TEST-ONLY bridge);
  tests/test_private_retention_action_integration.py;
  config/private-wire-vault-reference-manifest.json;
  .github/workflows/offline-discovery-audit.yml; .gitignore (only the fixed
  /pr71-private-vault-reference/ ignore); these spec/plan and taskboard docs.
- Ignored author/reviewer evidence and outside-Git authored temporary stores.

No R34 file, case/codec/model/coefficient/source policy/model pin, R29 module,
old journal/fixture/packet or other workflow is writable. Keep original V1/V2
store captures intact. Required evidence: default-deny0P/0destination; exact
two-process overlap/one P/one original create; crashes before/after P COMMIT,
before create, after destination COMMIT/before return; uncertain local COMMIT
0create; consumed0write restart; lost-P-return bootstrap without writer/clock
renewal; after-cutoff exact read/no-create; callback mutation/resource/column/
locator/type bounds and safe errors; post-slow-gate cutoff/rollback/DST UTC;
rehashed/cross-slot/profile P/E/M and copied receipt denial; no alias/new path
retry; saved old/new wires unchanged through ACTUAL Race34; missing genuine
receipt E0/public0; exact old V1/V2 case/store/ACK behavior/bytes.

This is local additive work under the owner's existing direction. Actual
source transfer/storage rights, real destination/runtime/security/retention,
global assignment, secrets/account allowance/cost, deployment/Access/public/
main and genuine-data completion remain separate unmet external Gates.
Authentic source/producer/time/cloud/global/official/scoring flags stay false.
