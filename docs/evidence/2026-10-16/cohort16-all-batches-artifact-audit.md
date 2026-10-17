# Day 16 cohort: independent all-batches artifact audit

Verdict: **PASS — zero actionable discrepancies in the local artifact scope below.**

Audited at 2026-10-15T17:37:46.256516+00:00 (UTC), using a separately implemented Python standard-library auditor. No product modules, restore helpers, tests, network, source or storage requests, Git commands, or subordinate agents were used. The only written files are this report and its machine-readable audit companion.

## Result and coverage

All 156 races in the frozen 2026-10-16 day universe are confirmed exactly once across 9 batches; zero races remain pending. The complete retained API objects agree with all 156 receipts. Each later batch preserves the complete earlier confirmed set, including its full canonical receipt hash, snapshot ID, nonce, and original timestamps.

Read every byte of all 320 original archive members (5,048,317 expanded bytes) and every corresponding cold-restored file. Independently verified each ZIP’s complete unique member inventory, regular-file metadata, sizes, CRCs, full payloads, archive SHA-256, and manifest hash against the recorded inventory. Parsed every JSON object with duplicate-key and nonfinite-number rejection. Original manifest/request/receipt files are canonical JSON; API witness raw whitespace and ordering were retained and comparison used the entire independently canonicalized object.

The source day feed is artifacts/local/day-restored-38761590081/race-ai-day.json; its independently computed canonical SHA-256 is 5dcddee8c61db1d1397805d19d559be66a12ce883c85528566f3a15d896e3923. All 156 source race IDs, closing times, and all six lane/registration/name/rating identities per race bind to the retained source feed. Each model’s complete input and explanation records bind to those same identities and source hash, including source observation and feature availability clocks.

Independently reconstructed both models for every race: 312 models and 37,440 ordered triple probabilities. For each model, checked all 120 distinct triples, normalization, strengths, and all six positional marginals by independently enumerating all 720 full finishing orders. Maximum absolute triple error was 1.7347234759768071e-17; maximum absolute positional marginal error was 1.1102230246251565e-16. Independently recomputed every complete model content hash and snapshot self-hash.

All timestamps are timezone-aware. The retained source observation precedes generation; generation precedes or equals cloud save; each save precedes its parent finish and the race cutoff. All source/generation/save/cutoff dates are the intended JST day. Each recorded local reconciliation follows its job finish and precedes the next batch start. Audit time follows every recorded reconciliation. These checks establish consistency of the retained clocks, not independently observed physical exhibition timing.

## Original batch inventories

| Batch / run | Original status | Saved + separately recovered | Prior preserved | Confirmed / pending | Files / expanded bytes | Reads / POSTs | Budget / elapsed seconds |
|---|---|---:|---:|---:|---:|---:|---:|
| 1 / 38764082826 | BATCH_LIMIT_REACHED | 24 + 0 | 0 | 24 / 132 | 49 / 740941 | 49 / 24 | 240.0 / 169.335016 |
| 2 / 38765469814 | TIME_LIMIT_REACHED | 21 + 0 | 24 | 45 / 111 | 43 / 658930 | 68 / 21 | 240.0 / 180.888314 |
| 3 / 38766928410 | STOPPED | 11 + 1 | 45 | 57 / 99 | 24 / 362172 | 70 / 12 | 240.0 / 149.082922 |
| 4 / 38768645246 | TIME_LIMIT_REACHED | 13 + 0 | 57 | 70 / 86 | 27 / 427569 | 85 / 13 | 240.0 / 183.916192 |
| 5 / 38770986021 | TIME_LIMIT_REACHED | 10 + 0 | 70 | 80 / 76 | 21 / 341279 | 92 / 10 | 240.0 / 180.612622 |
| 6 / 38772351868 | TIME_LIMIT_REACHED | 9 + 0 | 80 | 89 / 67 | 19 / 314540 | 100 / 9 | 240.0 / 184.115519 |
| 7 / 38774773544 | BATCH_LIMIT_REACHED | 24 + 0 | 89 | 113 / 43 | 49 / 775721 | 138 / 24 | 480.0 / 300.116527 |
| 8 / 38776652446 | BATCH_LIMIT_REACHED | 24 + 0 | 113 | 137 / 19 | 49 / 785248 | 162 / 24 | 480.0 / 344.051216 |
| 9 / 38777785588 | COMPLETED | 19 + 0 | 137 | 156 / 0 | 39 / 641917 | 176 / 19 | 480.0 / 341.641330 |

All original jobs retain the 24-write, 313-business-read, 49-file limits. The extended all-upcoming runs retain their explicit 480-second bound; earlier runs retain 240 seconds. Session issuer attempts/ready counts are separate from business reads. Producer commit remains 325ddce19ae999d626782a9929e6511c17d60ba1 throughout the manifests.

Original manifests record 940 business reads, 156 POST attempts, and zero official-source requests in total. Extended manifests record 6 session attempts / 6 sessions ready. These are independently reconciled artifact counters, not a new network observation.

| Run | ZIP bytes | ZIP SHA-256 | Manifest SHA-256 |
|---|---:|---|---|
| 38764082826 | 111200 | 8fd765e83f97f79a0b138760f5a23346e78329735dd159cd6204e368ac25e15c | ba94ec5b4265e64676e79de177ba254282403d64e82665999670d9049f4e1e19 |
| 38765469814 | 100714 | 58898256f96a133cea2e5ee5fac3b149ca467b6146f761f32844ea24b12ebbab | 257f64fb2a6596e17bb1ad92960d1b414714edfc62c71a66fe178022d1ae8dae |
| 38766928410 | 57062 | 2805d3f2d9b610557db8b48e2576418231ae51334c24ed09af3aa638761e50da | 5709f1fa6e38c025667be8e593775bab2b7014b93845d5e1735b3b333ea696b9 |
| 38768645246 | 67453 | 4a20251fcd34678e135e38a795bcdad961d7d4dd93049d6743d64916e39bcf95 | f28fb82546b4e283df2ebdd05ac1a1b1deacb95ebbea6e4d6cdd11d6a5164ab1 |
| 38770986021 | 54408 | fc96b35c0ebc1c074613b4027a11769c88186a01b57369326316b0e66995f4a3 | a423ffa441dab5c222f88fa5d9b891dcb57ea4d88f56a2fed1b338443a0d123c |
| 38772351868 | 51590 | bde43afdc399dc86ec0fe94b1e7ad6b81b0ce4195237346b2566efc4cf15dfdf | aa4423614b04a3e3ec6183ad1ef1c35253aa0ae2e929fb04a72e28b095b980d0 |
| 38774773544 | 121061 | 7cff7bddc957960b025dc0df920bc8e37a90246a3f35dfc1bc92acde0416f592 | e39afd934dc9328bd032593069b59cbe0fdc20ce1d9fe3226b74fec637968ef4 |
| 38776652446 | 123988 | 2659c8e0821113c5bacac972b331a05f07493c2141c9abc80534c4d90b9971f0 | 6ab4e4b93f9901c0f1a799efa191f321ef3cf8a2ca148e8a69f4f5c6b4b188a2 |
| 38777785588 | 103664 | bce15caab04cc577a3cc844b9e3a0407d095e8b4b1e97a78d29ed15b44eb85ef | e885724cacb22815bbe06dc7d4de29036fe804b276f7618eb4dd65e234a2ab84 |

## Failed batch and separate recovery

Run 38766928410 remains STOPPED after DAY_PUBLISH_HTTP_503, with its original 11 saved receipts, 45 preserved receipts, 70 business reads, 12 POST attempts, and all 24 original file bytes unchanged. It is not reclassified as a successful job.

The separate recovery archive and its source and cold-restored directories contain those same 24 bytes-identical original files plus the recovered receipt and recovery.json: 26 files, 396,038 expanded bytes. The ZIP is 64,845 bytes with SHA-256 e8587ecb83860a82a711aa5a7d605bcdf1940b2b057ebd4a41397584dde29a42. Every member and its full bytes passed independent comparison.

The recovered 20261016-08-06 receipt uses the original nonce 38766928410-1. Its exact-nonce and latest retained API responses agree with the same complete receipt; cloud_saved_at 2026-10-15T16:14:40.630344+00:00 precedes the original parent finish. The separate recorded recovery verification at 2026-10-15T16:20:12.315193+00:00 follows it. Recovery records 13 read-only GETs, zero POSTs, and zero official-source requests, separately from the original job counters. The recovered race enters the confirmed partition exactly once and all later batches preserve it.

## Aggregate evidence bindings

The following hashes bind the exact local inputs inspected by this audit; they are not signatures or source-authenticity claims.

- Progress file raw SHA-256: 5c7a5de9bb088394907d1b441b0dbd5688e3f12eb2ec0e86b558ccf962730dc9
- Complete original per-run member byte/hash map SHA-256: 53ccbb9070eb17f3d8ca9384f3772ea097f4c33012cc573ea91033f55c6e7390
- Complete race receipt/snapshot/nonce/raw-API-byte/hash/clock map SHA-256: df63b075e8210dcd8803e9b4a77bc616be1555a5faeeddbcb55883c51b23754e

## Limits and declined scope

All receipts and models remain research_only=true, validation_status=UNVALIDATED, purchase_decision=skip, with empty purchase recommendations; model uncertainty remains not_calibrated=true. Every reconciled batch retains physical_exhibition_phase_verified=false. Coverage and arithmetic integrity establish neither prospective accuracy, holdout/calibration success, nor model adoption or purchase authorization.

No source originals were reacquired, and no new source authenticity or original-source SHA recalculation is claimed. This audit uses immutable retained day, archive, restore, receipt, API witness, and progress artifacts; it does not independently prove network execution, deployment identity, or the root cause of the earlier HTTP 503. The reported batch-7 invalid reader response had no retained original status; this audit relies only on the complete retained matching API bodies, not a reconstructed status for that response.

The historical 118 forecasts from the prior JST day were outside this day-16 artifact audit and were not reread over the network or changed. Their previously established preservation evidence is not newly expanded here. No source dispatch, forecast generation, retry, restoration, deployment/CI action, credentials inspection, Git operation, or whole-project completion claim was performed.
