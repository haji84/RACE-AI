# Issue67 product position in the existing Compass canonical
## Goal
Map the authoritative issue67 M0-M4 and top-level acceptance to existing PR69/71/72, without claiming product completion or duplicating implementation.
## Scope / rulings
Same PR65, same canonical and Compass store. Read-only public GitHub observation. No automatic writeback, dispatch grants, merge, live data or deployment. Connector-only editing/testing because no suitable execution environment; replace local worktree/ledger scripts with this tracked plan and exact Actions receipts.
## Interfaces
Optional productPosition in the existing canonical snapshot: fixed issue67 identity, source updated times, M0-M4 requirements and ownership, full-goal acceptance reminders, exact PR heads and expected required CI steps. Checkpoint WorkState remains unchanged. validateProductPosition rejects self-certified acceptance and unrelated projects. assessProductPosition independently checks source freshness, exact PR heads and required completed job/step metadata; returns CONTRACT_VERIFIED only for synthetic contracts, always acceptance BLOCKED.
## Tasks
1. Add failing interface test to existing adapter suite; Actions must fail for missing export, not infrastructure.
2. Extend same adapter validation and read-only collection; add tests for source/head drift, skips/failure/unavailable, no product promotion, all milestone coverage and immutable snapshot.
3. Add sanitized revision3 productPosition preserving decisions and history with previous digest. Prove real Compass SQLite fresh bootstrap/export equality and full regression.
4. Independent review and exact-head CI verification. Record any meaningful gaps; no new authority.
## Evidence and completion
A successful adapter means context mapping/restoration, not full RACE acceptance. All five milestones remain BLOCKED until real acceptance evidence. Hit@8_all target98% includes all evaluable unpredicted races, remains unmeasured. M4 300 samples is not finalcompletion.
## Progress
Plan created from issue67 updated2026-10-23T09:31:12Z and issue68 updated2026-10-23T00:45:50Z. Prior canonical/head a5092aa. Step1 pending expected RED.

Step1 RED confirmed: c19b31521ac088fb972195fb5e9ff89ef473391a, run39935443263/job120353721015; existing9 PASS, missing product mapping export assertion FAIL. Implementing schema/collector/data/tests together. Ruling: preserve productPosition inside existing envelope rather than create extra Compass goal records, avoiding duplicate canonical state; per-goal assessment is a derived read-only report. Exact UI filenames verified in PR71 tree. Source digest computed over JSON.stringify(issue.body), same as adapter digest. No permissions changed.

Step2-3 verified at686e59d: run39936277310/job120356483473,14 tests PASS; actual Compass separate-process import/export equals revision3 canonical; live source digests current and PR69/71/72 required contracts verified, errors[], product still BLOCKED. Independent review confirmed canonical digest/decisions and no apparent sensitive content, but found latest-run race. Final fix RED observed at ea70a1b run39936502617/job120357240074 (14pass/1fail). Fix rechecks latest same-head workflow before accepting each contract receipt. Final GREEN/regression pending, no claim yet. No deferred review findings.
