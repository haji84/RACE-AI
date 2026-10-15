# Independent archived cohort artifact audit

**Verdict: PASS. Actionable discrepancies: 0.**

Audited at `2026-10-15T12:39:10.499430+00:00` using Python standard-library modules only (`pathlib`, `datetime`, `json`, `hashlib`, `math`, `itertools`, `zipfile`, `stat`, `zlib`). No product module, product helper, test fixture, or root arithmetic oracle was imported. Scores below were computed from the retained original 120-ticket distributions and each original result's own finish rows; original evaluation/report metrics were comparison targets only.

## Artifacts and full-byte checks

- Originals: `artifacts/local/name-bound-evaluation-restored-38715147499` (5 files) and `artifacts/local/name-bound-result-restored-38726468766` (6 files).
- Output: `artifacts/local/archived-cohort-output-20261015`.
- Cold restoration: `artifacts/local/archived-cohort-restored-20261015`.
- ZIP: `artifacts/local/archived-cohort-offline-20261015.zip`.
- Invocation witness: `artifacts/local/archived-cohort-execution-20261015.json`.

All 11 original files total **256,280 bytes** and match their output copies byte for byte. Output and cold restoration have exactly the same two input directories and **13 files / 263,426 bytes**. Every JSON file is duplicate-key-free and byte-identical to independently serialized canonical UTF-8 JSON. Original manifest inventories, index inventories, and witness file inventories match independent byte counts and SHA-256 calculations. No file exceeds 256,000 bytes; the combined original bytes stay below 8,000,000. Files/directories are regular and have no symlink/reparse metadata.

The ZIP has exactly 13 distinct expected relative file names, no directory extras, no encrypted/symlink/special members, and no traversal paths. Every decompressed member equals the output and cold-restored file in full. Member uncompressed sizes and CRC metadata agree; `ZipFile.testzip()` found no CRC failure. ZIP size: **57,994 bytes**; SHA-256: `1a3fa821375dc6c08d82d5cf5c233337723cab05165a8d52fc2936d78cec1235`.

| File | Bytes | SHA-256 |
|---|---:|---|
| `index.json` | 1759 | `f0a378115a409aa1094b59f984eed280e3fe6cc526978cb52949f9f615ca188e` |
| `input-001/evaluation.json` | 2813 | `e653f485a8d1910a05dbc58ba0db91d7a347148f8ba0fd7d1fcd24cdc0a84a46` |
| `input-001/forecast.json` | 113892 | `53d56c8445f1089b313e76c81c326a91b9bc2bf946d97dba6a67ba8eee6d3825` |
| `input-001/manifest.json` | 798 | `4575fdd9d8c8d4cdf4355c59079eedab4bf9021fda0d7b85fd3782c1d1ce1c0f` |
| `input-001/program.json` | 2171 | `84983f053ef03945006e212ba43d3ea44155f477d8f748b10ef26d5178c324b0` |
| `input-001/result.json` | 4958 | `65cf65d7a532220a8688fbb3e3051f5cd9bd96d32944be055fb9d9d9897ac2fe` |
| `input-002/evaluation.json` | 2815 | `3ff42a19f39eecdde14dcf191921ab2045d2b0d9bf6aeb6f169b92c82927050a` |
| `input-002/forecast.json` | 114084 | `ad1bbf97ae747ccf42488e5d1a85e430002fd94d0f706a344bf82ada9ec5f6bd` |
| `input-002/manifest.json` | 977 | `94de6970dee13d9ceac1c165010201f7527c9a168b1de10fbd81a6f2650eb667` |
| `input-002/program.json` | 2164 | `9c70fea0087ebbabcc1ebef1fb99aeda091660beb1d43ff64115edc266602b2c` |
| `input-002/request.json` | 5617 | `dd9c19c4dd17388ebd4638ff4a8aad2cbd25539761dd4caefbff7766016ee9b0` |
| `input-002/result.json` | 5991 | `c861d42201798ee5e498f1e8f7ecd01d318826ad83d7c58201ed94b04574dc92` |
| `report.json` | 5387 | `9614044549b83eef8bb52b93196c2549066c49af282222d42f359a73c821dc37` |

## Identity, clock, and counter checks

| Race | Result top three | Forecast nonce | Result publication nonce | Unchanged original evaluation as_of |
|---|---|---|---|---|
| 20261015-15-04 | 2-3-1 | 38699263834-1 | None | 2026-10-15T09:44:50.093237+00:00 |
| 20261015-15-07 | 2-1-4 | 38708771146-1 | 38726468766-1 | 2026-10-15T11:19:58.584791+00:00 |

Race and forecast identities, result proofs, own result finish ordering, all six lane/registration joins, full forecast receipt/snapshot hashes, baseline parent hashes, and publication request/finalized receipt bindings agree. The 7R publication request matches the complete original result snapshot and its own nonce/forecast/runner clock. Copied observations retain original evaluation clocks, source strings, parser strings, and all original content because their entire files match byte for byte.

The witness clock order is: start `2026-10-15T12:35:40.151096+00:00` <= aggregate/index `2026-10-15T12:35:40.216914+00:00` <= returned `2026-10-15T12:35:41.514798+00:00` <= root restoration `2026-10-15T12:35:42.881706+00:00` <= this independent audit. Each original evaluation is on its own Japan-local race day and precedes the aggregate; frozen forecasts were finalized before race close, and result capture/save precede their original evaluations after race close. The recorded invocation exit code is 0 for reviewed commit `953dd03a4f12e42dd770c84c22c5a7d000add9a2`. These invocation events are supported by the root witness; the independent artifact audit does not retroactively observe process execution.

Original 4R counters remain reads/posts/official-source **4/0/0**, budget 180; original 7R counters remain **5/1/1**, budget 240. New index/witness application/network/official-source counters are literal integer **0/0/0**. This audit performs no network or official-source requests. Copied original COMPLETED manifests remain historical records; the new index has no completion marker.

Report SHA-256: `9614044549b83eef8bb52b93196c2549066c49af282222d42f359a73c821dc37`; independently recomputed unsigned report snapshot: `1f6bad744471de2bc127d89cde4ac70914994c33c545874030af53cec90717f1`; independently reconstructed ordered model identity/parameter signature SHA-256: `f9a9deb74051ad258831a9c0dac870ef80fb8ee6d88df5bdb2a56b459e801725`. The two archives have identical complete signatures. Reconstructing the full aggregate independently, including observation rows, all score values, flags, identities, counts, and self-hash, yields exactly the saved canonical report bytes.

## Independent arithmetic

For each model/race, Brier = `math.fsum((p - indicator(ticket == observed_top3)) ** 2)` over all 120 ordered triples; log loss = `-math.log(p_observed)`; winner probability = the probability assigned to that race's own observed triple. Each distribution contains exactly the 120 unique permutations of six lanes taken three at a time, finite probabilities in (0,1), and total probability within 1e-12 of one. No metric comparison used a tolerance: all original per-race rows and aggregate rows match their independently computed canonical values exactly.

| Race | Phase | Multiclass Brier | Log loss | Winner probability | Brier minus baseline | Log loss minus baseline |
|---|---|---:|---:|---:|---:|---:|
| 20261015-15-04 | B_ONLY_BASELINE | 0.992292005849442 | 4.807484189586476 | 0.008168383974724941 | 0.0 | 0.0 |
| 20261015-15-04 | DISPLAY_V2 | 0.9905605908629309 | 4.711657624130029 | 0.008989863410291173 | -0.0017314149865110817 | -0.09582656545644674 |
| 20261015-15-04 | ORIGINAL_V2 | 0.9891705634232364 | 4.637163526472054 | 0.009685130318857897 | -0.0031214424262056006 | -0.1703206631144223 |
| 20261015-15-07 | B_ONLY_BASELINE | 0.9794557900275646 | 4.139447814436214 | 0.015931646301203212 | 0.0 | 0.0 |
| 20261015-15-07 | DISPLAY_V2 | 0.9770665599817572 | 4.041310846317648 | 0.017574419946130793 | -0.002389230045807378 | -0.09813696811856598 |
| 20261015-15-07 | ORIGINAL_V2 | 0.9717730225453218 | 3.8865363000214233 | 0.020516285367926268 | -0.007682767482242725 | -0.2529115144147909 |

All means use the same **N=2 races / 1 distinct Japan-local day (2026-10-15)**. Paired deltas are the mean of the two per-race phase-minus-baseline differences, not a separate cohort or 120 independent samples. There are no excluded observations.

| Phase | Mean Brier | Mean log loss | Mean winner probability | Mean paired Brier delta | Mean paired log-loss delta |
|---|---:|---:|---:|---:|---:|
| B_ONLY_BASELINE | 0.9858738979385033 | 4.473466002011345 | 0.012050015137964077 | 0.0 | 0.0 |
| DISPLAY_V2 | 0.983813575422344 | 4.376484235223838 | 0.013282141678210983 | -0.00206032251615923 | -0.09698176678750636 |
| ORIGINAL_V2 | 0.9804717929842791 | 4.2618499132467385 | 0.015100707843392083 | -0.005402104954224163 | -0.21161608876460658 |

## Limits and disposition

Zero actionable discrepancies were found. Research-only is true, validation remains UNVALIDATED, purchase decision remains skip with empty recommendations, physical exhibition timing remains false, holdout remains NOT_ESTABLISHED, calibration and model adoption remain NOT_EVALUATED. These guards are present in the exact independently reconstructed aggregate; larger or better-looking retrospective scores would not establish adoption. Formal completion remains false.

This audit establishes consistency of retained immutable artifacts and independent arithmetic. It does not establish new source authenticity, independently verified physical exhibition timing, prospective or held-out accuracy, calibration, statistical significance, ROI, model adoption, or dashboard integration. No new acquisition, cloud write, trusted-job dispatch, product CLI rerun, test run, browser/network access, Git mutation, or subagent occurred. CI/READY/API integration checks remain the root's separate responsibility. The only file written by this follow-up is this evidence document.
