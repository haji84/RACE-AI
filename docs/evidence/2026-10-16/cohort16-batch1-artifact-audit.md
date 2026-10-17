# Independent day-16 cohort batch-1 artifact audit

**Verdict: PASS. Actionable discrepancies: 0.**

Audit time `2026-10-15T16:00:37.607362+00:00` / `2026-10-16T01:00:37.607362+09:00`. Local standard-library-only audit; no product/helper imports, tests, network/source/storage requests, restore-helper rerun, Git operations, deletion, or subagent work. Only this evidence document was written.

## Whole ZIP, restoration, and API identity

Run **38764082826**; task-supplied job **116522639227**, artifact **11986978401**. The local summary/manifest bind the run/request identity; job/artifact IDs were not independently queried remotely. ZIP `artifacts/local/cohort-38764082826.zip`: **111,200 bytes**, SHA-256 `8fd765e83f97f79a0b138760f5a23346e78329735dd159cd6204e368ac25e15c`. Restoration `artifacts/local/cohort-restored-38764082826`: exactly **49 regular files / 740,941 bytes**, comprising manifest plus 24 requests and 24 receipts. The ZIP has precisely those 49 unique regular unencrypted members, no extras, and every full decompressed byte sequence matches the corresponding restoration. Every member size/CRC and the full ZIP CRC check pass.

Every restored JSON file is duplicate-key-free, finite, and byte-identical to independently serialized canonical UTF-8 JSON. All request/receipt byte counts and full hashes match the manifest inventory. Manifest SHA-256: `ba94ec5b4265e64676e79de177ba254282403d64e82665999670d9049f4e1e19`. Every full model content hash and every full snapshot self-hash was independently recalculated. All 24 saved `cohort-api-20261016-*.json` bodies canonicalize to the entire corresponding receipt, preserving all model fields, inputs, source clocks, and identities; raw API whitespace is not confused with canonical byte identity.

## Day-16 progress seed and exact cohort partition

Universe: **156** unique races from the independently hash-bound day16 saved feed (canonical SHA-256 `5dcddee8c61db1d1397805d19d559be66a12ce883c85528566f3a15d896e3923`). Selection equals all 156 races sorted by actual close time then race ID. The first 24 are exactly the attempted/newly saved set. The remaining 132 are exactly both pending and not attempted, with no overlap or omissions. **24 new, 0 preserved, 0 skipped, 132 pending**. This is a bounded first batch, not completion of the 156-race cohort or the full project.

Manifest status is BATCH_LIMIT_REACHED with null failure fields. Bounds/counters: max24 write slots, max313 reads, max240 seconds; actual **49 application reads, 24 POST attempts, 0 official-source requests**, 24 write slots. The manifest structure is consistent with one day read plus 24 existence reads plus 24 readbacks, but no raw transport trace was supplied to independently recount those calls. Zero official-source scope is not zero storage/application activity.

## Source, identity, and real clock binding

Producer commit is `325ddce19ae999d626782a9929e6511c17d60ba1`; request nonce `38764082826-1`. All 24 receipt and snapshot source hashes bind to retained day16 B-archive digest `87dce616b2207807b5671ff875d9aedda2c46bd9709a7dfdcb3117a42bb2b66f`, URL `https://www1.mbrace.or.jp/od2/B/202610/b261016.lzh`, observed at `2026-10-15T15:35:23.711762+00:00`. All six original lane/name/registration/national-rating rows for each race match the complete saved day program exactly. Model feature inputs and explanations independently match those identities, source references, source available/captured/generated clocks, and expected strengths. Original source bodies are unavailable, so this is retained provenance consistency, not a new source-authenticity audit.

Actual start `2026-10-15T15:52:26.003556+00:00`; finish `2026-10-15T15:55:15.338572+00:00`. Recorded elapsed 169.335033 seconds agrees with wall-clock difference within one millisecond (separately measured clocks). Every source observation precedes generation, every generation precedes/equal its cloud save, and every save is within the batch and before its own close. All clocks belong to 16 October JST. All 156 selected races remained upcoming through batch finish. No original time was rewritten or inferred from race close.

| Newly saved race | Snapshot ID | Actual cloud save UTC |
|---|---|---|
| 20261016-14-01 | `c2f996a96bd0d46529615c500ef0aa96858b19305b0ac2649c4105fcd12c8402` | 2026-10-15T15:52:34.176159+00:00 |
| 20261016-21-01 | `e5b53a2b97d15d2fabd396561732d7d2732d21c89dd2284cbbd9c3d10a2b70e8` | 2026-10-15T15:52:40.967706+00:00 |
| 20261016-10-01 | `7a61c08230e6670a37b90961c80b852bbd9e8be6943d382cee6858fc26b67d79` | 2026-10-15T15:52:47.950626+00:00 |
| 20261016-14-02 | `3501a859f067ca36e119a9618825241476b271d0e1ea7f51256548e98861b4cf` | 2026-10-15T15:52:55.533703+00:00 |
| 20261016-21-02 | `fd44e6aae74d762498a48e45f39aa7007c4ff91bdec879d271e92a2e97d0c909` | 2026-10-15T15:53:01.860932+00:00 |
| 20261016-10-02 | `de4aedf10e3e7bbbe6f51f85d68e9b679c4de75c57a242cadbd376e98ca911c4` | 2026-10-15T15:53:08.854243+00:00 |
| 20261016-14-03 | `afd807c779d67056684787f0ec9d69129f3e1232f544fa6f965a4c8f6b82c62a` | 2026-10-15T15:53:16.074479+00:00 |
| 20261016-21-03 | `57757d3f0658d511050fc74359d2fba3022b414944243da7ada7b2fefec59093` | 2026-10-15T15:53:22.370602+00:00 |
| 20261016-10-03 | `cd3caf269c098bfe39299a392c92f721101acba8a27dc4349d7d25793bd43672` | 2026-10-15T15:53:28.666661+00:00 |
| 20261016-14-04 | `7dddd9b95262be5cc84dc3879c53c69c96f70a5b5b02d15e14bb3f19c9436dc6` | 2026-10-15T15:53:35.018119+00:00 |
| 20261016-21-04 | `0a117b4e8b580b6d0af98e527388bc7ccf51d9ac52cc582a596867017faec430` | 2026-10-15T15:53:42.604329+00:00 |
| 20261016-10-04 | `3015c7b75eec2be14b790c68291fe553a377ff15cfff3e69786c2b1632dbcd58` | 2026-10-15T15:53:49.085772+00:00 |
| 20261016-08-01 | `b8dd67fad2d1273ebec0dde884e4db49d6adbd234e7236f2541083dde10fd7f5` | 2026-10-15T15:53:55.981957+00:00 |
| 20261016-14-05 | `a2f705de638f19fe2a60923c4c4ba057342ec9aae100e1a0e526a5a92fc015e8` | 2026-10-15T15:54:02.764810+00:00 |
| 20261016-04-01 | `4917fda42c26e009d2c31762f26a71b8c45c075487954179df105fef56d854f2` | 2026-10-15T15:54:10.468787+00:00 |
| 20261016-09-01 | `8c308c70a7f454934d9a4c6a8c80c3706aa95241516a5039b95cea370813397b` | 2026-10-15T15:54:17.215207+00:00 |
| 20261016-21-05 | `f74613781ef82d89922cdfa85f75d3df6322167584a3c530278699f6e9d1a9ce` | 2026-10-15T15:54:23.059220+00:00 |
| 20261016-10-05 | `767ba8e04a3fbdf0edb2e626b203e344dfda2e86930bfa303016a4445882f24e` | 2026-10-15T15:54:29.221470+00:00 |
| 20261016-13-01 | `84217fefe1e706a610c2caf7b132a272a1d1b6d81f805c1c5bf7b59d724cedb0` | 2026-10-15T15:54:36.750137+00:00 |
| 20261016-08-02 | `c0c7780f0e5a89ff12a3bb909a6dae0f82bdf3f859659fe0746d78123ecc0f30` | 2026-10-15T15:54:42.938438+00:00 |
| 20261016-02-01 | `21f0e2c82ec427a41a12dc6b8f2e1c1623cdec6de0d7c2e99fdcc782d1c19a23` | 2026-10-15T15:54:50.322856+00:00 |
| 20261016-14-06 | `4797601cd2c88e31f195d41e1abdbcb7202a4670550b1a5c025c469dd506b14f` | 2026-10-15T15:54:57.308404+00:00 |
| 20261016-04-02 | `1e98bb8a206d4d750a17a6d7e774fdbabd1f69794dc2dd866d5d52076d9cf335` | 2026-10-15T15:55:03.821149+00:00 |
| 20261016-09-02 | `39b09d46f0cdf9945e16915a0a554373dcb8d42f1a7f2ad1e89d7b83d21353dd` | 2026-10-15T15:55:11.277796+00:00 |

## Independent probability reconstruction

For every race, the uniform model uses six strengths of 1.0; the rating model uses `max(saved_B_national_win_rate, 0.01)` per lane. Strengths were derived from the independently bound day program, not trusted from the prediction output. Both models are version 1. For each ordered triple `(a,b,c)`, independently computed `w[a]/W * w[b]/(W-w[a]) * w[c]/(W-w[a]-w[b])`. All **48 models / 5,760 triple probabilities** match within absolute tolerance 1e-14; maximum measured absolute error **1.3877787807814457e-17**. Every model contains all 120 distinct ordered triples, finite probabilities in (0,1), normalized within 1e-12.

Also independently enumerated all 720 complete six-lane orders for each model, using successive remaining-weight denominators. All six finishing-position marginal probabilities and top-three marginals match within 1e-13; maximum measured positional marginal absolute error **1.1102230246251565e-16**. Tiny discrepancies are floating-point evaluation-order differences, not material probability mismatches. Hash equality checks use exact canonical bytes, not numeric tolerances.

## Complete receipt/request and saved API inventory

| Race | Request bytes / SHA-256 | Receipt bytes / SHA-256 | API raw bytes / SHA-256 |
|---|---|---|
| 20261016-14-01 | 124 / `9cffffca64f1d50ab07869621c38bd26e39b53b90eb36d289aa781c151abcf3b` | 29751 / `0d12977efba6f93a5aa6ffb70b98e86b9836423dc62ff09a93925eb99a02c84c` | 32037 / `ec42010501d472fc129d026cb67efe4fa871d202f0f0e959e6556dce5d8965a0` |
| 20261016-21-01 | 124 / `c68b15645f0931879063bfe820d508c0208cdf4e1fa30c0b64a44e81d4cedb3c` | 29779 / `5b255dc29eb4e18950866b351736c581e3af363622563d68ee4fe274d44990b8` | 32065 / `13616649fb27ffc80acdeddfd1d4ee140b9837dd288c8465deb4a823ca6b2210` |
| 20261016-10-01 | 124 / `dc5f5e3b5491a34400914c57d2131fd29850c7588a3691396250ec4c48e31636` | 29761 / `6b2bed0af1fea7a6948fb7b2661f77c04deefb1952dd0e76ea2a1554d54f990a` | 32047 / `0d59af3b55966a3cbff7645ab0f87a6aa8cc79b80edad2d0fd13d063696efde8` |
| 20261016-14-02 | 124 / `a5c1c3f20c901c24dcd5b369caaa883ca504e4a3837594eeedc4ce6e474b9ecd` | 29761 / `2a65f8f84cad3955006b50ba140b3d825d6e7927e83a545daded487bb2e545f6` | 32047 / `c83d7fea6ed2120969d3ba8d456307bb2cd276c2c3f6f12c53c5927678f5673b` |
| 20261016-21-02 | 124 / `7733598f64c4b6e8c5332dad6b5f75e07a4917a7724f71fc92bf4ad791e23f3c` | 29763 / `2ec969aa0d034e4504b00568d17aebec0a731f1cd9fdf9c8fda001dc58e60009` | 32049 / `35b439ef8c6665d20b59723434914a430f6a1964a8c3455303a03b496547fd34` |
| 20261016-10-02 | 124 / `9d0faf4fb325286449a73177d4014dfbb359eee5209bf84dd60786737595d4bc` | 29762 / `3b382e712a99b2bbecd4fadd2304dacb2fa7d14c41a2a39f11c6556ede372898` | 32048 / `b12dfaf7ca7b74409894ee1246359089170244168cca297fbc802111c6548cfa` |
| 20261016-14-03 | 124 / `b857e32db671c7631e8beca3f33218db7dd04a4aed82f00a40f8aad1cd127457` | 29749 / `5496b6ca329b1c1088857df0195d653eca0d66260e6f54b760d832ac92a600df` | 32035 / `3dec8cc28f9265df26dfb1f510811d66fba857cf3d5e9b6a58e4c55c12420fef` |
| 20261016-21-03 | 124 / `c1e9dca6909d1bae00863346fdc0ad8332d1165667484eb6812078542fdf6237` | 29753 / `c0440cff49157f4935cb44dc02a9149240c57b247c80b38e7c278fd0d09d7629` | 32039 / `6a6d2b410ba69c6b4e42911506ea5035dc7a0012cadbb46b8002d6048ec94b85` |
| 20261016-10-03 | 124 / `a4ea4a73dde898da77503fd02f979325f85ac299db82da1cc00e0e3cd800b836` | 29747 / `b8ac1ba04b05790fa42cfae4e42d4d1f028d1e44d95fb738a996f35955a23401` | 32033 / `c3bd062a4c9919da4834dfbfdbb3c7d06a78078e1f20e78e771780eb6308b688` |
| 20261016-14-04 | 124 / `478e693334946a094b29f402fbce249516a0a4eace29387318205dc9fe21c516` | 29762 / `cdc565f37b0235949cbb61cc51555ab046f173a1b3994fce73793994cccab2a5` | 32048 / `52e6c5287acde4ca8bbe920270f2331d10a2535098159dc52d85bcf7813c0b90` |
| 20261016-21-04 | 124 / `b7d72f09cdb09883e89f28923741714373b6c792af750374175941df4bf1782a` | 29746 / `facb0d2eafb6664b04c0228f7a33adca073f31c18963f88a143aa9fc1ad9ce41` | 32032 / `5007e15cdf82a7a2f02979ad13539750d3d4471c384f284407f1789eae3e2181` |
| 20261016-10-04 | 124 / `8c783e9f6e2082d29a89e8bdfbeef97473cf16ef2a238187fa6a344cdcfa06ee` | 29759 / `06a7bfacdbe4e4438221182cdf974135ca181c869e63123d2d1491482d966569` | 32045 / `69fcca97db15fab396d21feb03f1cbcc9866660d292831da0a3641cc1f64bf09` |
| 20261016-08-01 | 124 / `1f6dfc9aeafe65e88997d9c5d258e2654175295c53a1f29056c0e9cd6047ec58` | 29769 / `926e32349262fe5686b02bd71d2f059013f67a4af6697ec7d73d4667db664291` | 32055 / `6d1aa5136ba216c82faa1415423dfd690077f5b87bac3c57b7058af6cb224af5` |
| 20261016-14-05 | 124 / `f6ec1d650820fbc19b9714db0cc6737f754957d8de5cf83b174df33773dd0cce` | 29772 / `d769c90c61050c5665317972bcf2009a94932d492172d69b0859cf1f2aae25e0` | 32058 / `e1412ac8615d88a64cdf946661543665d110e8cbf98745618008828c365116e1` |
| 20261016-04-01 | 124 / `98fe049591268d26871695426b42e90d7ed6cc4d3139fb41b3904b66d36f0ae3` | 29743 / `3295ebc9adcbf46965a0c7b2e87e8da600c1a3e298e83269c0fc385d4a5f05ed` | 32029 / `921505fd2602a31ad6997ce28c985885dd976b7cdd39e335f85fbefa8ccfae83` |
| 20261016-09-01 | 124 / `5104848f1d04c88a6635bf8480a5234492969765c1a16dd8a8e82b0db34778bc` | 29780 / `f9f384f5c1deef7b5831cdb6e54b009bb904575ea4d44ad0f4817c93f1dd710e` | 32066 / `0a7f0a0ed87010da89ca5f5a179b907dd2fb055d93a026805292b71f74dbf897` |
| 20261016-21-05 | 124 / `737ae79f679c9ba6ed6d3387070e98e541ebc18b263073689e259d9315b97aa9` | 29750 / `7b80872e647cac42d73f9b1d8aa76174bee6cf48989a6776090a1b5f60dc6e5d` | 32036 / `94e08b199b8cec5512efd20dafd30d0b02b2b7bae37ddc7a7286589ea5904cda` |
| 20261016-10-05 | 124 / `7a6443af21d0f2c1ec5f94e077df2ea715146f7920a6e2ddadcb3fb989038b81` | 29752 / `e6091e8ad7c8d2a02f17f60a2ccff5fcd6c66b654d41cd77f316dc2498fe9b10` | 32038 / `c9e6cd2c8cd3e314b9adc28abcb0e0f839ced5b526a4fd60783613c07446e7d8` |
| 20261016-13-01 | 124 / `b79c44899549fdb94157f107da2913d6b7389d03861baa400f3c83547d3ae479` | 29730 / `eb5a5d3f9792b644c762daaccd9452f4486bfa9c9c81fe0050570246ef6b477d` | 32016 / `246b1082f492f342898e71b70bc9835c7447f68297ee02929f664dd0c21f7234` |
| 20261016-08-02 | 124 / `9956384d64ecd2a44c02e8a14b0d44e9c3ac7153ea8068100c56b41b72506337` | 29779 / `2f96f5c84ccb07d32745890ce1c61a12baf76051ec6eb3956b604663b17eb9c3` | 32065 / `8a1a4b45b7590a241e0457ac4e3a270b1ac886c72ff55250e84754c778625410` |
| 20261016-02-01 | 124 / `c70222d1189e204d129330a8f50058d3f0e6a85c7ad361cd02daf034a4a897fc` | 29750 / `93e9890d193415e16bd708c74eb29a871c4a04dd59cba6af47cb54c760d98f65` | 32036 / `9d5402e05fb32b82eaf712c78fb2fe759df06c1cdcc8c981ec09f837f684d72c` |
| 20261016-14-06 | 124 / `5aa72e5c7438e275d80277e4f9c7abc3cf3972af10467470861daca5f4dfb565` | 29742 / `29e0f89ca79079d70a2125475bb955108305743f9483f0fcd20a12db3272299e` | 32028 / `0a625a8ec7db0b467985f242db69a35c148b65ad060219300f082de88c571213` |
| 20261016-04-02 | 124 / `581e6648679b6e9992dacbf5ba0855d0503589836d654b9abbd96b2a412c3f19` | 29743 / `4cd9aa631d33bfc9a72926329c67a10adf9499e967abfa4d813701d33da52e17` | 32029 / `7ff7e4b82fa03d734d52456fe5e97f5bb9ca8c57aec7d29fc978331d0686fe02` |
| 20261016-09-02 | 124 / `d871bbf5441101f51089b6f9955783a75b25f8b1b60b7f70cfe320ff3c855b16` | 29754 / `21da48886ae22ec1bc29a33f1eb5e8294626a33b339f17a073bb9bb4b39c7b3f` | 32040 / `e76ed83d34e62cd1a24290377b70617fe6cfbfb847bd2ef28c204c98f8eacc9d` |

## Limits and disposition

All manifest/snapshot/model research guards remain UNVALIDATED, skip, and empty purchase recommendations. Snapshots/models are research-only; models state unvalidated accuracy and not calibrated. This audit establishes 24 immutable B-program baseline receipts and their internal probability consistency; it does not establish physical exhibition phase, result labels, scored accuracy, prospective validation completion, calibration, adoption, or full project completion. Saved API bodies prove complete content agreement, not independently measured HTTP status or response-time/deployment provenance without separate transport witnesses.

The requested audit is complete with zero discrepancies. The 132 pending identities remain pending; this report does not itself dispatch batch2 or grant further source/operational authority.
