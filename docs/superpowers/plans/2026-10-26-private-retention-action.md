# Private Retention Action V3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task after root authorization. Steps use checkbox (`- [ ]`) syntax for tracking. C implements; D independently reviews; root alone writes Git.

**Goal:** Commit one irreversible same-owner private action before one exact
local whole-wire create, with read-only recovery and no automatic public release.

**Architecture:** A fixed prospective PRIVATE_ACTION_V3 extends the existing
attempt owner with one immutable P row and reuses its C/E/public machinery.
Production has two narrow injected operations with no default runtime. A
separate TEST-ONLY bridge demonstrates actual pinned Race34 native storage.

**Tech Stack:** Existing Python3.12/SQLite/stdlib and native Node24 test runtime;
no new dependency, service, credential, provider or model.

**Spec:** docs/P0_PRIVATE_RETENTION_ACTION_V3_20261026.md.

## Global Constraints

- Baseline PR72 8c813eedab0cc534a0f1388dfde147761a88d155; clean before spec writes.
- PRIVATE_ACTION_V3/user_version3; application_id0x52415355; same owner, one P.
- LEGACY_V1/RETAINED_V2 defaults, bytes, SQL/domains/ACK/replay remain exact.
- Race34 commit9aeb2b425de9d05a44cb31f72a242a5111ada80a and exact three hashes
  in the spec; native adapter TEST-ONLY; original model_source_sha40 unchanged.
- Whole wire<=4MiB; P/proof/metadata<=64KiB; Race34 claim<=8KiB/eight512KiB chunks.
- Candidate admission and final post-gate row guard are separate immutable identities.
- No wire copy in attemptDB, private ACK/history, reset/resend/new nonce or registry.
- Missing genuine protected-reader/independent receipt means E0/public0.
- No model/source/cloud/account/old-packet work. No Git by C or D.

## Review Focus

1. Existing P after a lost return needs no writer/declaration/clock renewal;
   bootstrap exact row SHA and recover read-only from the same store (Task2).
2. Delayed final admission and uncertain COMMIT must not expose a future row
   SHA early or permit a writer; zero-write consumed state survives restart (Task2).
3. Rehashed/copied P/E/M and cross-slot/profile rows must fail semantically
   before external receipt callbacks, with old bytes preserved (Tasks1/3).
4. A valid-looking local readback never becomes E or independent proof;
   fixed Python/Node result conversion preserves original bytes (Tasks3/4).
5. Arbitrary binding/result/private SQLite errors and oversized metadata must
   not leak or allocate unbounded private material (Tasks2/4).

---

### Task1: Fixed profile and immutable P structure

**Files:** Modify race_ai/permissioned_case_submission.py and
race_ai/retained_case_submission.py; create race_ai/private_retention_action.py
and tests/test_private_retention_action.py. No R29/case/model/R34 changes.

**Interfaces:** Existing retained operations accept only the fixed new
submission_contract keyword/default specified in the spec; new E/public/
witness calls also require exact expected_private_action_sha256 for V3.
Private module exports only consume_private_retention_action and
read_private_retention_action with the spec signatures.

- [ ] Write failing `test_v3_profile_is_explicit_and_old_stores_refuse_it` and
  `test_default_private_gates_leave_no_p_or_destination_calls`: assert user
  versions1/2 are not migrated/adopted, V3 is explicit, missing required fresh
  declaration/create/gates leaves P absent and create/read counts0.
- [ ] Run only the new focused tests on the established root Python3.12
  interpreter, preserving meaningful absent-function/module RED in ignored
  artifacts/race35-author-red-*.log before production implementation.
- [ ] Implement fixed profile constants/domains/fieldsets and exact V3 SQL:
  old base+C/E plus singleton submission_private_action and its update/delete/
  reinsert guards. No global profile switching or duplicated C/E state machine.
- [ ] Implement scalar SQL size/type admission before metadata fetch and
  strict finite canonical P candidate/row semantic reconstruction per spec.
- [ ] Verify focused GREEN and `test_rehashed_missing_or_cross_slot_p_is_denied`
  plus foreign/crossed-schema byte-preservation assertions. Preserve failures.

### Task2: Consume once, bootstrap and exact read recovery

**Files:** New private_retention_action.py and its focused tests; minimal
shared core/retained hooks already in Task1 only.

**Interfaces:** consume_private_retention_action(...) builds candidate/R/vault
claim from actual case/C, records P, calls private_create(claim,bytes) at most1.
read_private_retention_action(...) requires final P row SHA and calls
private_read(claim,locator) at most1. Counts are wrapper invocations only.

- [ ] Write failing `test_only_normal_p_commit_owner_calls_create_once`,
  `test_prior_p_bootstraps_without_clock_or_writer_renewal` and
  `test_recovery_never_creates_when_p_or_object_is_missing` with exact field/
  status/count expectations from the spec. Reuse bounded authored existing
  fixture helpers; saved-original integration must not rerun producers.
- [ ] Implement fresh source/owner/coordinator admission via existing R29,
  separate cutoff/roster and exact action/adapter callbacks. All missing fresh
  requirements deny BEFORE P. Prior P lookup runs before live writer checks.
- [ ] Under BEGIN IMMEDIATE/FULL recheck the same store's C/R/P and gates,
  admit the immutable candidate, sample/hash final guard after last callbacks,
  INSERT/COMMIT P. Only the normal COMMIT-returning invocation owns one create.
- [ ] Implement PRE_PRIVATE_CREATE fresh gates/edge; denial/error/interrupt
  preserves consumed P, including0writer calls. Validate the exact frozen
  Race34 result/bytes/false flags without making receipt/ACK/E.
- [ ] Implement explicit reader-only recovery after cutoff and bounded safe
  summary/errors; no missing-store creation, source/write renewal or repair.
- [ ] Write/run `test_slow_guard_cutoff_and_clock_rollback`,
  `test_uncertain_p_commit_calls_no_writer`, `test_consumed_zero_write_restart`,
  `test_two_processes_force_overlap_one_p_one_create`, and real process crashes
  before/after P COMMIT/before create/after destination commit/before return.
  Record unique RED/GREEN logs and verify no second create after restart.
- [ ] Exercise callback mutation/oversized strings, column TEXT/BLOB/type
  corruption, locator/body/result promotion and private exception suppression.

### Task3: P before E/public without changing old behavior

**Files:** Existing two core/retained files and focused private-action tests.

**Interfaces:** V3 E/M/prerequisite/summary/public action and witness recovery
bind final P row SHA/guard; original guarded writer/ACK/resolver is reused.

- [ ] Write failing `test_v3_e_requires_p_before_receipt_callback`,
  `test_receipt_before_final_p_guard_denied`, and
  `test_local_readback_without_genuine_e_keeps_public_zero`.
- [ ] Implement exact V3 E/M additions and chronology using actual stored P.
  Keep public release separate from private write admissions. No automatic E
  from local result; preserve original normal-return-only public ACK/barrier.
- [ ] Run focused GREEN and affected old V1/V2 tests only as appropriate;
  root separately owns immutable old case/store/ACK fixture replay and the
  final full suite. Do not erase baseline failures or relabel old evidence.

### Task4: Root's fixed local integration and workflow

**Files (root only):** scripts/verify_private_retention_action_synthetic.py;
scripts/private_retention_action_local_vault.mjs;
tests/test_private_retention_action_integration.py;
config/private-wire-vault-reference-manifest.json;
.github/workflows/offline-discovery-audit.yml; .gitignore exact reference ignore.

**Interfaces:** Root binds the two supplied Python callables to ACTUAL
unchanged createLocalPrivateWire/readLocalPrivateWire and test-only native
openLocalPrivateWireD1 from pinned9aeb bytes. Product imports no test helper.

- [ ] Materialize the fixed three-file reference and verify its exact commit/
  module/schema/test-adapter hashes, without changing original model pins.
- [ ] Build a no-listener test-only Node bridge with fixed executable/module
  paths, outside-Git4MiB binary input/output,64KiB control/result metadata,
  8KiB stdout summary and stderr discarded. One30s spawn-to-reap deadline,
  kill/reap/join without reset; no private wire in command line/stdout/logs.
- [ ] Write a failing original V1/V2 saved-wire integration that invokes the
  actual vault through the owner seam, proves exact whole bytes and lost-ACK
  GET-only recovery, and asserts no genuine evidence => E0/public0. Keep
  original saved inputs ignored/local and do not rerun their producers.
- [ ] Hosted CI uses authored fixtures/native Node24 and pinned reference;
  add only exact path filters and the focused test/integration command. No
  manual source workflow/provider/HTTP/cloud resource or deployment.

### Task5: Independent review and sole-writer closeout

**Files:** Ignored author/D/A evidence; root-owned taskboard/closeout artifacts.

- [ ] C freezes exact owned source/test hashes with focused count/runtime,
  RED/GREEN/crash/concurrency evidence and remaining limits. No self-approval.
- [ ] D independently criticizes frozen bytes, reproduces important defects;
  C repairs only concrete authorized findings with preserved RED/GREEN.
- [ ] Root verifies actual saved-wire bridge, old V1/V2 byte fixtures and full
  tests once at final bytes. A checks original data/assets/pins unchanged.
- [ ] Root alone handles fresh source-smoke/deploy guards, allowed-path
  staging, normal existing-PR push, exact-head CI and packet/restore audit.
  C/D never commit/push. No completion claim before those separate gates.

Spec/plan only at this stage; root and D must accept this exact freeze before
Task1. No production runtime promotion or stronger genuine-data claim follows
from local functional acceptance.
