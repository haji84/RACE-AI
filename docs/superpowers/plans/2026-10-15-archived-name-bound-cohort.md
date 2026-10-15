# Archived name-bound cohort implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strictly replay retained immutable research archives and compute honest common-race aggregate metrics without new source or cloud I/O.
**Architecture:** Separate pure historical archive contract; local bounded/exclusive copy-and-verify CLI. Existing current-day validators, forecasts, result stores and UI unchanged.
**Tech Stack:** Python standard library and existing pure web contracts; unittest. No dependency installation.
**Spec:** docs/superpowers/specs/2026-10-15-archived-name-bound-cohort.md

## Global Constraints

- Exact schemas, bounds, interfaces, constants and clocks from spec. Never source/network/auth/remote/browser/subagents in implementers.
- Owner-selected cwd/branch; command-local Codex author; one implementation worker at a time. Commit own files only, full report in ignored plan workspace.
- Preserve both manual-only source-smoke copies, trustedff95/325/psh5 pins, all118 predictions and completed sources. UNVALIDATED/skip/[] always.

## Review Focus

1. Historical replay must not become live clock backdating or new predictions; unchanged stored as_of plus independent actual audit clock, Task1.
2. A malformed excluded archive must reject rather than silently disappear, Task1.
3. Same race under another nonce and differing model signatures must not inflate/blend sample, Task1.
4. Original manifest I/O counters vs new offline0 counters remain distinct, Tasks1/2.
5. Symlink/foreign/partial output and late write/close failure must not overwrite or emit success, Task2.

### Task 1: Pure archive replay and common-race aggregate

**Files:** Create race_ai/name_bound_archive.py and tests/test_name_bound_archive.py only.
**Interfaces:** build_archived_name_bound_cohort(entries, *, now); validate_archived_name_bound_cohort(report, entries, *, now). Exact entry/manifest/report/observation/model schemas, constants and hashing in spec. No caller imports/network.

- [ ] RED: synthetic five/six-file inputs replay full existing frozen forecasts/labels/reports; two race IDs, historical multi-day replay and strict audit future/naive/rollback cases. No source or filefixture dependencies outside synthetic test helpers. Original as_of and every input immutable.
- [ ] RED: exact1..24/8MB/perfile256k/output256k; missing/extra/duplicate/type/nonfinite/hash/program/parent/request/nonce/clock/manifest/counters/signature/coefficients/repaired tampering reject. Complete old4/0/0 vs new5/1/1 manifests remain distinct.
- [ ] RED: valid excluded statuses produce empty/real exclusions; corrupted excluded record/report rejects. Duplicate race across nonces rejects. Common cohort only, distinctdays notoutcomes; math.fsum means and paired differences independent expected arithmetic, allN=0 fields. No holdout/calibration/adoption/physical claim even multi-day/highN.
- [ ] Implement minimal strict pure module using existing pure report/envelope builders at immutable stored as_of; no old current-day caller verifier. Focused GREEN; self-review and commit only own files. Report exact RED/GREEN, schemas/interfaces, limitations. Full suite waits Task2 to avoid duplicate whole-suite run.

### Task 2: Exclusive local archive CLI and full restore

**Files:** Create scripts/evaluate_name_bound_archive.py and tests/test_evaluate_name_bound_archive.py only.
**Interfaces:** run(archive_dirs, output_dir, *, execute=False); verify_output(folder, *, now). Consumes Task1 exact entry contract. CLI/output/index/counters in spec; no new execution-completion flag. Error fixed NAME_BOUND_ARCHIVE_STOPPED and CLI exit2.

- [ ] RED: dry0clock/FS/network; exact5/6files and canonical duplicate-free JSON/bounds; all inputs validated before output; nonsymlink ancestry/output root, exclusive child writes; foreign directory and unknown/partial/oversized/repaired archive rejects without changes.
- [ ] RED: real temp-directory complete2cohort copies all11originalfiles plusreport/index byte-for-byte and restore; inputorder deterministic; full index/file/report hashing/types/counters/ids and aggregate replay reject rehashed tampering. Fresh actual audit clock nondecreasing and beyond stored as_of.
- [ ] RED: failed open/write/readback/close/final verify cannot return or print success, may keep owned partial files, never truncates/removes/retries/overwrites. No network/auth/subprocess/source calls or absolute input paths in evidence/error text. Distinguish old input source counters from current literal0.
- [ ] Implement GREEN, focused bothtasks; run full Python and existing187JS once, git diff --check; self-review and commit own files. No operational execution on actual archives, no push/trusted mutation/source/browser/otheragents. Report interfaces/counts/concerns to root.

## Root integration gate

Per-task spec/quality reviews then one broad most-capable review. Root actual offline run on completed4R/7R archives, full output/index/ZIP restore, independent stdlib paired metrics and clock/identity audit. No new source, no write to cloud/trustedworkflow. Selected APIs unchanged; latest exactWindows/Linux CI/READY before PR64/evidence/state/heartbeat update. Correct stale current chapter228 label requirement only (historical sections remain historical). Archive/delete only ownSDDworkspace after exhaustive rulings export. Branch/main/Production preserved; formal completion false.
