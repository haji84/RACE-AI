# Day 16 06:35 refresh: independent artifact audit

Verdict: **PASS; zero actionable discrepancies in the local artifact scope.**

Audited at 2026-10-15T21:40:34.120596+00:00 (JST 2026-10-16). Scope is the new authorized six-hour refresh only: run 38811179135, job 116684495572, artifact 12007734183. Used an independent Python standard-library implementation. Read the program_digest identity rule and its normalization dependencies in web/race_contract.py and the root verifier as reference; imported and executed neither. No product modules, tests, network/API/source/storage requests, dispatches, credentials, restore helpers, Git operations, or prior completed audits were run. Only this UTF-8 LF report was written.

## Full archive, restore, and API checks

Independently read the entire 32,594-byte ZIP and verified its SHA-256 against both the supplied value and the retained GitHub artifact digest. It contains exactly one regular, unencrypted member, race-ai-day.json. Checked unique exact inventory, full decompression/CRC, member size, and equality of every byte with the single cold-restored file. The original 349,880-byte file and both complete API witness objects passed strict JSON parsing with duplicate-key and nonfinite-number rejection.

The canonical whole-feed representation is 349,879 bytes, SHA-256 c9bcf98abe5f0ac68428a7a3c1c633864121556ab95c7059636a8a353bc24d57. Both retained API bodies canonicalize to that exact complete representation. Each raw API witness is 380,520 bytes with the same raw hash shown below. The raw restored file has a terminal LF but also differs in key order from sorted canonical JSON: its one-byte length difference does not imply raw equality to canonical-plus-LF. Originals and API formatting were preserved.

| Retained input | Bytes | SHA-256 |
|---|---:|---|
| day-refresh-dispatch-20261016-0635-accepted.json | 503 | d21cbf27f3980ecfe6e87104b06f8364d988899824ea442e7d23895549f1211d |
| day-refresh-preflight-20261016-0635.json | 380520 | 4f37b5c265c1093ca257944d2463c0049eb99d240d07cdab49a38ba58432945b |
| day-restored-38811179135/race-ai-day.json | 349880 | 37ee661ba478376d8af9d734af0868f7533315ba0edf4004fae8076bec8d1d28 |
| day16-refresh0635-api-publisher.json | 380520 | ab64db24d061a25760f2e5248c15d8139bc315b884ed8e743a1a4647100c84b3 |
| day16-refresh0635-api-reader.json | 380520 | ab64db24d061a25760f2e5248c15d8139bc315b884ed8e743a1a4647100c84b3 |
| day16-refresh0635-safe-log.json | 1886 | 7a41a6471ec6005560f9a13eeb48c490ec3bf9dc92a51e30a29cd9ec0859121f |
| day16-refresh0635-summary.json | 21891 | 79791f6a6209508b1803feeb4d3cec843f7ada3c2a52ebb18869daecbfb52ca8 |
| official-day-38811179135.zip | 32594 | a3e0ddf51002f343a5b9ac12d3e73e6f0c2e8e0e7e67cdd2d9f9f56d62689b0f |

## All venue states and program identities

Checked all 24 unique venue codes 01–24. Active venues are 01, 02, 03, 04, 08, 09, 10, 13, 14, 19, 20, 21, and 24: each is READY, no_event=false, listed in the complete day index, and has exactly races 01–12. The other 11 venues are NO_EVENT, no_event=true, not listed in that complete index, and have no races. Every venue binds the new index URL, hash, observation time, and schedule-verification state.

Independently enumerated 156 unique dated race IDs and 936 boats. Every race has six unique lanes 1–6 and six distinct four-digit registration IDs, a nonempty normalized name, and a cutoff on JST 2026-10-16. Every race binds the new B-archive URL/hash/observation clock. All preview_available values remain false; average_st, display_time, and preview_course remain null throughout.

Independently reconstructed each program identity from race_id, the aware cutoff normalized to UTC microseconds, and all six lane/registration/name tuples in lane order. Names use NFKC normalization followed by whitespace removal. Compared all complete identity objects to the retained old preflight, then recomputed all 156 digest values; all agree with the independently computed old values and the summary map. This identity rule excludes mutable display fields and source-acquisition hashes.

The canonical SHA-256 of the complete 156-entry identity-digest map is fcf8350d6ed5e134290ef9d2aeee27bd633a2ca7379e9e8cb334e1b7c3822e72. The old preflight canonical SHA-256 is 5dcddee8c61db1d1397805d19d559be66a12ce883c85528566f3a15d896e3923. No old baseline snapshot or model was rewritten or regenerated.

## Source scope and clock order

The two recorded official sources are exactly the dated complete index https://www.boatrace.jp/owpc/pc/race/index?hd=20261016 and B-program archive https://www1.mbrace.or.jp/od2/B/202610/b261016.lzh. Feed maximum_source_requests, the safe approval log, and the summary reconcile to this two-source scope. Shared Blob scratch verification and normalized day publication/readback are separate operations, not additional official-source reads.

The new index source hash is 21a44e5922557558a8dcb4e08028efa6120074291f0a39c51d73c8366bf595c8. The B downloaded-archive hash changed from 87dce616b2207807b5671ff875d9aedda2c46bd9709a7dfdcb3117a42bb2b66f to 6333bf9a833946d11a3df3b69398fb690cce6c01ecd842faf777dd2aacce7f1e. Its retained extracted-text SHA-256 stayed 8770bbd043b61d5a77103e3a9b33acf5e067033e1646b9de2f447f03985fb8f5. Raw archive equality is not claimed. Source originals were not retained; these source hashes are retained provenance bindings and cannot be independently recalculated from original source bytes in this audit.

| Event | UTC |
|---|---|
| Previous last real acquisition | 2026-10-15T15:35:23.711762+00:00 |
| Six-hour gate | 2026-10-15T21:35:23.711762+00:00 |
| Dispatch started | 2026-10-15T21:36:30.883566+00:00 |
| Dispatch accepted | 2026-10-15T21:36:37.483125+00:00 |
| New index observed | 2026-10-15T21:37:03.137380+00:00 |
| New B archive observed | 2026-10-15T21:37:05.445882+00:00 |
| Publisher API verified | 2026-10-15T21:37:13.218851+00:00 |
| Runner backup restored | 2026-10-15T21:37:15.090116+00:00 |
| Root two-API receipt upper bound | 2026-10-15T21:37:53+00:00 |
| Root local audit | 2026-10-15T21:38:46.313521+00:00 |

All clocks are timezone-aware and satisfy the six-hour gate and causal ordering; all acquisition/dispatch clocks fall on JST 2026-10-16. Independently measured previous-to-dispatch 21667.171804 seconds, previous-to-first-new-source 21699.425618 seconds, and previous-to-last-new-source 21701.73412 seconds. The new sources were observed at 06:37 JST. The next six-hour eligibility is **2026-10-16 12:37:05.445882 JST** (2026-10-16T12:37:05.445882+09:00); this is an eligibility calculation, not dispatch authorization.

Checked the safe log's complete publisher canonical hash/version pathname, 24/156/936 counts, and runner restored-byte/hash record. Retained GitHub artifact/run metadata, dispatch ledger, and summary agree on e071480037d918714ea87288e9bc9598480f256d / workflow blob 74f4d7423fd50bafb5fefcb368f3c36f0243f3c9, worker a4889c443d168c45df253c28086ebed7ba566e18, and producer 325ddce19ae999d626782a9929e6511c17d60ba1. These are consistency checks of retained records, not independent live deployment or network verification.

## Limits and unchanged decision status

The retained summary reports zero new baseline/numeric predictions and zero verified physical exhibition pairs, no baseline source reacquisition, no repeat dispatch, and source_originals_retained=false. This day-feed refresh provides no new numeric/video forecast or physical timing evidence. UNVALIDATED, purchase_decision=skip, empty purchase recommendations, and formal_completion=false remain explicit. The overall project remains unfinished; no prospective accuracy, precision, calibration, model adoption, or purchase claim follows.

Only the new refresh artifacts and its required retained preflight were audited. Historical cohort/name-proof audits were not repeated. No acquisition, API call, publication, restoration, source authenticity proof, authorization change, or workflow/code mutation was performed.

## Dispatch-ledger lifecycle clarification

At 2026-10-15T21:43:10.003165+00:00 (separate local lifecycle check), verified that the original mutable dispatch ledger had advanced after the full audit to COMPLETED_VERIFIED_DO_NOT_REDISPATCH. Root reconstructed the accepted-stage record as artifacts/local/day-refresh-dispatch-20261016-0635-accepted.json. This copy is exactly 503 bytes with SHA-256 d21cbf27f3980ecfe6e87104b06f8364d988899824ea442e7d23895549f1211d, matching the original accepted-stage bytes measured during the full audit, including their CRLF terminal newline. The catalog now names this preserved copy.

The completed ledger retains every accepted-stage field except status and adds the matching run/job/artifact IDs, last real acquisition, all-156 identity/full-restore/API-match confirmations, and zero independent findings. Its bytes at this lifecycle check were 812 with SHA-256 213bd82b77039172bf17d4d48ec74079135cd4c1ae700a2edf192f87f7587117. The original full-audit clock, observations, inputs, and conclusions above are unchanged. This narrow local byte/field consistency check did not rerun source, API, archive, restore, or model audits.
