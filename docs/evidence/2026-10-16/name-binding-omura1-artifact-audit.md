# Independent Omura1 name-artifact audit

Verdict: **PASS within retained-artifact scope; open actionable findings: 0.** Recorded `2026-10-16T04:43:11.439143+00:00`. Used only Python standard-library code; imported no app validator, executed no helper/old CLI, made no network/source/job request and changed no product/data/proof file. All **14 input files** were checked for byte stability (13 in the initial pass and the additional publisher capture afterward). Only this report was written.

ZIP is **8,109 bytes**, SHA256 `c9d4d25a736901da45f378e5717bbebff2aff7a5534bcc67b48ed2f1eb00a604`. CRC passes. Its exact inventory is five ordinary, unencrypted path-free JSON files, totaling **38,673 bytes**. Each decompressed body matches its restored file byte for byte; all members are duplicate-key-free finite canonical UTF-8 JSON. All four manifest backup size/hash pairs match. The manifest's own digest matches the summary.

| File | Bytes | SHA256 |
| --- | ---: | --- |
| baseline.json | 29,757 | `37d32e700e8e8cdb7f11423d78a960f45f90d46ee7f9c67b248ee0fcf2e1fd65` |
| manifest.json | 789 | `99f4423d591b56f0a874a94737a6acdf1675781b1653a144b52a8fac7c004195` |
| name-proof.json | 2,254 | `334cdf68df6552a91e7378d9eb8e16e8c59b7ea7dc6db2baf1a61ff51b2fb8d8` |
| receipt.json | 3,392 | `a79253c4be36805b42d02d3b87eaa88c9a63807cf273f03681bd8e8310ba008b` |
| request.json | 2,481 | `81223d6df28d7066be60b565edd9c4ce23c7a4f6e77e3f9c9a5dfbe944a0eb72` |

Request/manifest/receipt/finalization agree on **20261016-24-01**, request **38851355587-1** and publisher `325ddce19ae999d626782a9929e6511c17d60ba1`. The summary ties this request to run 38851355587. External job/artifact identity and GitHub transport metadata are outside the supplied bundle and were not re-queried.

Recomputed proof self-hash **0cb68e41979ac81c6ca0e976c57b7b9e23620d77adec059783aaba5d60e375b8**, baseline snapshot self-hash **c0a0ce505a24c46fb48c2a1fde819f1f88ff938eb9cb829bac919257cf906b2f**, and finalization receipt hash **72990f98de8c5a96dc400a627d4163d10c81a6b440525900029309d8b8d1fb63**. Request snapshot, standalone proof and receipt snapshot are identical. All baseline request/snapshot/B-source/program-identity parent links agree.

## Six own bindings

Independently compared all six lanes/registrations against the exact current-day Omura1 race and original baseline program boats. Binding program names are literally equal to both own program copies; observed source names literally equal the verified full names. NFKC plus whitespace normalization gives **six EXACT_CANONICAL_NAME** relations, with no aliases, fuzzy matching or replacement characters.

| Lane | Registration | Canonical name |
| --- | --- | --- |
| 1 | 4422 | 永井亮次 |
| 2 | 3964 | 宮地博士 |
| 3 | 4315 | 山崎昂介 |
| 4 | 4747 | 山戸信二 |
| 5 | 3564 | 桑原啓 |
| 6 | 4094 | 中島真二 |

Recomputed own race/cutoff/six-identity digest **cd83be78aafa1abdbe23f77823f9df35739c2f44537d02e53d1c1edaf12effd4**. It matches the proof, receipt and finalization. The preflight complete day retains canonical **349,882 bytes / e7350fb5e3f6e0bc94f228e9c0820abbe2aea2280a1af71f7869b4d0bbff7ff5**. The baseline's historical B-source hash **87dce616b2207807b5671ff875d9aedda2c46bd9709a7dfdcb3117a42bb2b66f** is preserved separately from the current day archive/extracted-text hashes; current race identity compatibility is established by the six bindings and cutoff, not by equating those distinct source hashes.

## Complete baseline/API retention and clocks

Bundled baseline equals the full original `cohort-restored-38774773544/20261016-24-01.receipt.json`: **29,757 bytes**, SHA256 **37d32e700e8e8cdb7f11423d78a960f45f90d46ee7f9c67b248ee0fcf2e1fd65**, request **38774773544-1**. New baseline API capture is byte-identical to the old complete cohort API capture; both normalize to those original canonical bytes. Fixed, latest and publisher name API captures are byte-identical to each other and all three normalize exactly to the **3,392-byte** bundled envelope, SHA256 **a79253c4be36805b42d02d3b87eaa88c9a63807cf273f03681bd8e8310ba008b**. The saved API files contain an added final newline; equality is stated at the complete canonical-body level.

The original baseline generation/cloud save precedes name capture. Name clock chain is **04:35:18.062048 UTC capture → 04:35:18.084436 generated → 04:35:18.085678 runner save → 04:35:22.057820 cloud save → 04:35:23.083812 confirmed**, all before the own cutoff **06:16 UTC / 15:16 JST**. Confirmation is **6,036.916188 seconds before close**. Availability equals capture and upstream publication time remains null. All new clocks fall on the correct JST race date.

## Scope limits and research gates

Manifest records COMPLETED, no failure reason, 1 official source request, 1 POST, 4 reads and 180-second runtime limit. These are retained recorder claims, not a reconstruction of all network traffic. Source URL is the exact official Omura1 racelist identity and its retained parser/name rows are internally consistent; the disposed raw source body was **not** retrieved or hashed. Declared source-body SHA **24db1d97fad50c6c8b510734bd04762125d1eb7af914f02f732ad6445bb29168** is a retained link only.

This establishes preserved bytes, exact own canonical name/registration relations and the recorded pre-cutoff clock chain. It does **not** establish a physical exhibition-before observation, a display/original forecast pair, result evaluation, model validation or general alias-prediction integration. Research gates remain **UNVALIDATED / skip / []**; alias_prediction_integration_complete remains false. SHA checks establish retained integrity, not public-key authenticity or independent source truth.

Publisher capture added to independent scope at `2026-10-16T04:43:39.284052+00:00`: complete saved bytes **3,393**, SHA256 `2a6b51a2fa8faa67a2a4029abb3982b8bdaf8124be787c9d827997bb4d66aab4`; all three complete API captures match and their canonical envelope matches the original backup. No new request was made by this auditor.
