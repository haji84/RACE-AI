# Owner recipient sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Steps use checkbox syntax for tracking.

**Goal:** Synchronize the existing PDCA journal using the already-configured Actions owner key, and connect its unchanged predictions to the existing personal UI.

**Architecture:** Owner-secret-derived X25519 recipient encrypts transport without exporting the secret. Existing AES-GCM checkpoint remains canonical; producer/consumer Actions jobs prove restore, then pinned canonical Git readback verifies it. A pure private projection feeds existing UI variants.

**Tech Stack:** Python 3.11+, pinned cryptography, SQLite, existing Git/Actions workflow and vanilla UI.

**Spec:** `docs/superpowers/specs/2026-11-06-owner-recipient-sync-design.md`

## Global Constraints

- Same public GitHub repository only; encrypted originals, no key export/new provider/permissions/fees/bets/main merge/active worker restart.
- Owner's existing production key is the root, with domain-separated receiving key only. Exact cipher/source/run/head pins and non-force trusted-parent updates.
- Preserve every original and revision. Missing or bad previous state stops instead of resetting. No forecast regeneration.
- Existing website only; external URL question pending. Display remains private research without invented metrics.

## Review Focus

- A substituted receiver can disclose originals: require independent artifact/document pin and reviewed run/head before encryption.
- Previous generation concurrent advance: refuse unexpected canonical head and missing prior generations.
- A public artifact may contain bogus self-claims: authenticate artifact API identity/digest, bind producer and separate consumer proof, restore canonical bytes on Actions.
- Large malformed inputs: bound before allocation/decompression, preserve strict canonical encodings, never echo exception payloads.
- UI model/variant collisions: preserve both baseline/history as separate selections and never duplicate or alter original tickets.

### Task 1: Recipient transport and Actions handoff

Files: create `race_ai/boat_pdca_recipient.py`, `scripts/boat_pdca_transfer.py`, `tests/test_boat_pdca_recipient.py`; modify existing Git transport and `.github/workflows/forecast-audit-ui.yml`; add default public transfer input under `audit/state/`.

Interfaces: `receiver_document(key, run_id, source_head)`, `encrypt_transfer(state_path, receiver, *, expected_receiver_sha, output)`, `receive_transfer(pointer, root, *, key, previous_pointer)`, `verify_received_checkpoint(folder, root, *, key)`; all fixed-schema metadata and private files. Only count-only proof/ciphertext is returned to public artifacts.

- [ ] Add failing invented-data tests for exact receiver identity/pin, production-only state, full-size transport roundtrip and tamper/wrong root, canonical Base64/JSON/scope/path/hash bounds, no plaintext/key logs.
- [ ] Implement using X25519/HKDF/AESGCM, existing `sqlite_snapshot`, `restore_state`, `_audit` and `_no_regression`; preserve existing production checkpoint format.
- [ ] Extend validated Git transport to exactly two allowed state refs; add trusted initialization/parent checks for publication of already-authenticated encrypted output. Test local bare Git/non-force/immutable generation paths.
- [ ] Add receiver/producer/consumer jobs in the existing workflow with existing `contents:read`, same-repo PR guard, encrypted-only/count-only artifacts and explicit HOLDs.
- [ ] Run focused tests and commit. Fresh security/correctness review before using actual data; fix confirmed important findings with regressions.
- [ ] Publish code to existing PR, authenticate receiver artifact through GitHub metadata and independently hashed ZIP, deliver real journal encrypted to that recipient.
- [ ] Verify producer/second-runner output, publish canonical encrypted generation, update pinned production input and observe real production readback success.

### Task 2: Existing personal UI projection

Files: create `race_ai/boat_pdca_projection.py`, `tests/test_boat_pdca_projection.py`; modify only existing local service/UI boundary as needed; document actual preview/URL.

Interfaces: `project_pdca(state) -> RACE_AI_PRIVATE_CYCLE_VIEW_V1`, exact stored model outputs with `variant` distinguishing baseline/history. Source identifiers refer to retained pair/receipt bytes, never forged artifact receipts.

- [ ] Add failing invented pair tests for unchanged Top8/hash/timestamps/participants, both variants, pending/revised results and bad state refusal.
- [ ] Implement pure projection and prove the existing browser normalizer accepts it without granting formal eligibility.
- [ ] Connect private projection read to the existing API/import path; do not start native collection or interfere with active worker.
- [ ] Compare actual 156-race projection against original bytes; verify representative UI model/variant selection with invented-data browser checks.
- [ ] Apply to the user's identified existing site or private preview; verify actual rendered saved predictions before claiming website availability.

### Final verification

- [ ] Focused and full relevant Python/Node checks, existing GitHub CI, final fresh review and evidence ledger. Keep actual synchronization, UI availability and unresolved URL/privacy/retention/accuracy gates explicit.
