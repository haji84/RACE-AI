# Independent day-16 batch-3 recovery artifact audit

**Recovery verdict: PASS. Actionable discrepancies: 0. Original job remains FAILED / STOPPED.**

Independent audit time 2026-10-15T16:23:04.271690+00:00 / 2026-10-16T01:23:04.271690+09:00. Local Python standard library only; no product/helper imports or execution, tests, source/network/storage requests, Git changes, deletion, subagents, or re-publication. The recovery helper was inspected statically, not executed by this auditor. Only this evidence document was written.

## Original failure is preserved

Original run **38766928410**, job **116532464797**, artifact **11990057052** stopped with DAY_PUBLISH_HTTP_503 at race **20261016-08-06**. The immutable manifest still says STOPPED, failure target unchanged, with **11 saved, 45 preserved, 100 pending**, 99 not attempted, 12 POST attempts, 70 application reads, 12 write slots, and zero official-source requests. All 24 original files remain unchanged, including the target request with nonce 38766928410-1 and the STOPPED manifest. This audit does not relabel the failed original job as successful.

| Bundle | Files | Expanded bytes | ZIP bytes | ZIP SHA-256 |
|---|---:|---:|---:|---|
| Original cohort-38766928410.zip | 24 | 362172 | 57062 | 2805d3f2d9b610557db8b48e2576418231ae51334c24ed09af3aa638761e50da |
| Separate cohort16-recovery-38766928410.zip | 26 | 396038 | 64845 | e8587ecb83860a82a711aa5a7d605bcdf1940b2b057ebd4a41397584dde29a42 |

The original ZIP and its restoration were compared completely; all member names, bytes, sizes, CRCs, and regular unencrypted member modes pass. The recovery ZIP, recovery directory, and separate cold-restored directory match in full for all 26 files. Its exact additional files are 20261016-08-06.receipt.json and recovery.json; every other byte comes unchanged from the original 24-file archive. All JSON is finite, duplicate-key-free, and exact canonical UTF-8 in both bundles.

Original manifest SHA-256: 5709f1fa6e38c025667be8e593775bab2b7014b93845d5e1735b3b333ea696b9. Recovered receipt canonical SHA-256: 03105b49fdb906072df2f7425076079171497de11673d1f67e08bb8fba5010e6. Recovery JSON SHA-256: 7939aeb0c9021c44041c7deb1a30c7731816c3e6479b6cfdedf10cea87d6fc13. Outer verification-record raw SHA-256: 5abd7923c8934343ed6d49443a928e88a751d095a832d4e6b35e5b92e98c0bd8. All original manifest request/receipt inventory entries, recovery original-file inventory entries, and both outer inventories match independent full-byte hashes.

## Uncertain POST recovered through reads only

Both retained target API bodies, exact request and latest, canonicalize to the same entire receipt. The subsequently saved generic target API body also matches. The request nonce remains 38766928410-1; snapshot ID remains e9c2dc70d48a5b2e36186007bead68309ded751d595f2c23b46d0ddf9527c111. The cloud save time is the original 2026-10-15T16:14:40.630344+00:00, earlier than original job finish 2026-10-15T16:14:43.547617+00:00. No recovery timestamp replaces the original save or generation time.

The separate actual verification time is 2026-10-15T16:20:12.315193+00:00, after the failed job finished and before this audit. Recovery counters record **13 API GETs, 0 new POSTs, 0 new official-source requests**, separately from original **70 reads / 12 POSTs / 0 official-source requests**. Thirteen is consistent with the retained two target API witnesses plus eleven successful-receipt witnesses. These are recorded operational counters/content witnesses; no raw HTTP request trace or independent remote history was queried to recount calls or prove response-status provenance.

## Independent identity, probability, and prior-chain checks

All eleven original successful receipts and the additional recovered receipt bind to the full retained day16 program, canonical SHA-256 5dcddee8c61db1d1397805d19d559be66a12ce883c85528566f3a15d896e3923. For every one of the 12 races, all six original lane/name/registration/national-rating rows match, source URL/hash/observation clocks match the frozen B source, and the entire snapshot/model hashes recalculate correctly. Feature inputs and explanations bind to those exact source clocks and independently derived strengths. All 12 saved current API bodies match entire receipts; no partial field comparison was used.

For each of the 24 models, strengths were independently derived from the frozen day program: six ones for uniform, max(national_win_rate,0.01) for rating. Recomputed every one of the **2,880 ordered-triple probabilities** with the three-stage Plackett-Luce formula. All exhaustive 120-ticket sets are unique, finite, positive, normalized, and agree within 1e-14 absolute tolerance; maximum observed difference is **1.0408340855860843e-17**. Hash checks remain exact byte comparisons. This numerical verification is not an accuracy/adoption claim.

Every source observation precedes batch start; each generated/as-of clock falls within the actual batch, precedes/equal its own cloud save, and the cloud save precedes original job finish and its race close. All relevant clocks belong to 16 October JST. No clock was backdated or replaced.

All **45 preserved receipts** were independently located in original batch1/batch2 archives and checked against their original inventory hashes. Their full bytes/hashes, request IDs, snapshot IDs, and save/generation/as-of clocks match the original batch3 preserved rows. Their current saved API bodies and the existing progress-file hash chain also match exactly. No prior prediction was replaced.

## Progress disposition

The original manifest ordered universe equals the full **156** day16 race IDs sorted by close time/race ID. Its first 45 are preserved, the following 11 are confirmed in the original job, and the next race is the uncertain target; original pending remains 100. Adding the independently recovered target once produces **57 confirmed / 99 pending**, with no overlap, duplication, omission, new nonce, or skipped race. The outer recovery record has exactly this pending complement. At audit time the progress file still contains only its original two batches and 45 confirmations; the recovery helper has not advanced it.

| Reconciled batch3 race | Snapshot ID | Original cloud save UTC | Canonical receipt SHA-256 |
|---|---|---|---|
| 20261016-02-04 | 22bb1170cd9f5959ca09c68bb0fbdcb70fe195ecc6a3dcfb98ff3af90c7adf88 | 2026-10-15T16:13:33.211305+00:00 | aeac52084c7545e9e9ce71352a3cbaef0f72552cd78922ed3fc2cab70dae858e |
| 20261016-02-05 | 683065caec3eb03eb00229d79846557dbbb9d45f314503df56721e75f55637c7 | 2026-10-15T16:14:33.986358+00:00 | 0eef30e5ac74b07c55ccd709ef2bb260ba7ef635add986eabfd9dd5114e24583 |
| 20261016-03-04 | f6795eb6f4798e0fe29b04c5d53ab6b37aff1aa664b8f2294dbd3d5a7c3a656e | 2026-10-15T16:14:14.193169+00:00 | 8645eefdc12aeb12d0097cfae546935e9413afce66177341d5a4c59ccc6d471f |
| 20261016-04-05 | 1d6172eeec9e30322792c52306a376d6a8c6c553884d1f155a745ad1cff65fd0 | 2026-10-15T16:13:54.266506+00:00 | 1d89a18e603fb74c66445a3b332d786a05839b4eaef9753658ccd79d7f9269c6 |
| 20261016-08-05 | 41c0f9c64e38baa54242f10485351d1f05ea77f6131d95cc58aeabd2cbaddb26 | 2026-10-15T16:13:39.705263+00:00 | baf7f1d9e74ac44721645838251be8b45f292f8e3607af54979b52e07ffdfd05 |
| 20261016-08-06 | e9c2dc70d48a5b2e36186007bead68309ded751d595f2c23b46d0ddf9527c111 | 2026-10-15T16:14:40.630344+00:00 | 03105b49fdb906072df2f7425076079171497de11673d1f67e08bb8fba5010e6 |
| 20261016-09-05 | f5a188e155d5c068cb9eca210e0da5625e989cc626284ba36520b9a2a767a1a4 | 2026-10-15T16:14:00.920450+00:00 | 26b9b3d2a4bd01148561cc84dfb3405831fc9ac30b850eae56b868e2664ada11 |
| 20261016-10-08 | 223f847afdc8d2ef489bbb006a9f662bfe4a6d52af0a22456fc8f0a3e1873a38 | 2026-10-15T16:13:26.363873+00:00 | 2e2af5f679335159d152c5d1d39c6aa2d5bc1d61a8b512746633e6f57c46f74d |
| 20261016-10-09 | 65d7d382a592e30e549777d0066822b3526164eb1ac01e6187665866fa32649e | 2026-10-15T16:14:26.107594+00:00 | 58c844abddd98db2eee48cceb57b5ec8d37d8a9edfd8f63929cbc685918b806e |
| 20261016-13-05 | bf18e7ab745b196a2cdcdb2ed30689640d12945828c003f35a9034a8d598d1dd | 2026-10-15T16:14:08.263990+00:00 | 3b05279d6f00d2910a37098f8c451d3d9aae661ed2226f043a3053a0d642f009 |
| 20261016-14-09 | 44a98b58af6484a7225b487b53aa65ef0298fe9a6633c51b8e4e799fc4ef0720 | 2026-10-15T16:13:47.139702+00:00 | c655e6bdfb071316a8e3af09e7e686773993b84bb839e1f5b876f485304b470b |
| 20261016-21-09 | 86e6d51f5dc6d96a8bd029d25d0a5cf491b20956a7497e93c0dd5c0b81043014 | 2026-10-15T16:14:19.532041+00:00 | c2ce7ea08ec57f853e51ff68dde1cceda7e631f43e3b6e772f1cbfe4e09c9ee8 |

## Limits

Recovery metadata and every checked prediction remain UNVALIDATED, skip, empty recommendations, and research-only where present; calibration remains unestablished. Physical exhibition phase remains false and formal completion false in the recovery record. This establishes consistent immutable receipt recovery, not source authenticity, physical timing, labels/results, predictive performance, model adoption, or full project completion. Source originals were not retained. The supplied job/artifact IDs and actual HTTP outcome attribution remain root/record witnesses, not fresh remote queries.

The artifact recovery gate is clean. The original failed job and its manifest remain failed/STOPPED; any subsequent progress reconciliation or next job is a separate root-owned authorized action.
