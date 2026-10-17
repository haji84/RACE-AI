# Independent day16 12:48 refresh-artifact audit

Verdict: **PASS within retained-evidence scope; open actionable findings: 0.** Recorded `2026-10-16T04:04:27.170699+00:00`. This audit read only the new actual refresh evidence and its retained preflight, plus static serialization/digest definitions for interpretation. It made no requests, read no credentials, executed no dispatcher/verifier top-level body, reran no source/job/old CLI/test suite, restored no old archive, and changed no source/data files. Ten actual evidence inputs were reread and remained byte-stable. Only this report was written.

## Complete bytes and attribution

| Object | Bytes | SHA256 |
| --- | ---: | --- |
| ZIP | 32,625 | `a76f47d5501831c5e2649ad76c691af32aa59844ac0ecaf2f62bd4d9f1464541` |
| Complete raw backup | 349,883 | `5c8d282fbd39adb2332985d02dd412e569a3826e44158408c8e58ac6a55e11eb` |
| Complete sorted canonical API body | 349,882 | `e7350fb5e3f6e0bc94f228e9c0820abbe2aea2280a1af71f7869b4d0bbff7ff5` |

ZIP CRC passes; the exact single entry is ordinary, unencrypted `race-ai-day.json`, with no path/directory/symlink entry. All decompressed bytes equal the restored file. The captured GitHub artifact size/digest exactly match the ZIP. Artifact `12023628915` is tied in captured metadata to run `38847861450`, branch `feat/boat-oidc-probe-auth`, head `5a38336727c452ef0ba796f56b68434fe7b59837`. The captured run is completed/success, workflow_dispatch, attempt 1. Job `116802344691` is recorded in the summary; a separate job metadata capture was not included in this audit.

Dispatcher/summary pins agree on workflow blob `44e997bae629f29f4a48eded0d694fefe8bfdabd`, worker `a4889c443d168c45df253c28086ebed7ba566e18`, publisher `325ddce19ae999d626782a9929e6511c17d60ba1`, and reader `03c57daeec0319c810a8ba68320aa41040161479`. Safe-log retained bodies agree on publisher, API canonical digest/counts and raw backup digest/size. Both complete saved API files are byte-identical to each other and normalize to the complete restored backup. Duplicate JSON keys and nonfinite values were rejected during independent parsing.

## Program facts and mutable refresh data

The day is `2026-10-16`, approved with the unchanged publication review, containing **all 24 venue states, 13 active venues, 156 unique races and 936 boats**. Active venues each have 12 races; every race has six unique lanes/registrations and a same-JST-day cutoff.

Independently reconstructed every race/cutoff/normalized-name/registration/lane program digest using standard-library code. All **156** match both the preflight body and the summary's digest inventory; the canonical digest-map SHA256 is `fcf8350d6ed5e134290ef9d2aeee27bd633a2ca7379e9e8cb334e1b7c3822e72`. Complete race program objects also remain identical after removing only their observation clocks, including all boat fields, cutoff and program-source fields. The program archive SHA and extracted program-text SHA remain unchanged.

The entire feed is refreshed, not byte-identical to its predecessor: observation clocks changed, schedule-page source hashes changed, and `current_race_no` changed at 9 venues. These mutable schedule/progress changes do not change the 156 program identities. No other schema/inventory/value changes were found. The summary correctly records 2 official source requests as distinct from GitHub evidence retrieval and Blob probe/publication/readback operations. Those counters are retained recorder evidence, not newly reconstructed network traffic.

## Actual clock chain

- Previous real acquisition: `2026-10-15T21:37:05.445882+00:00`; six-hour eligibility: `2026-10-16T03:37:05.445882+00:00`.
- Fresh witness: `03:54:23+00:00`, status 200, exact hl3rank6i reader/deployment identity and old complete canonical body **349,879 / c9bcf98abe5f0ac68428a7a3c1c633864121556ab95c7059636a8a353bc24d57**.
- Dispatch start: `03:54:24.397746+00:00`; acceptance: `03:54:30.237459+00:00`. Start is 22,638.951864 seconds after the prior acquisition; the witness is only 7.237459 seconds old at acceptance. The one-shot ledger remains `DISPATCH_ACCEPTED_DO_NOT_REDISPATCH`.
- Actual acquisition begins `03:54:48.281585+00:00` and ends **`03:54:49.102563+00:00`**. The latter is 22,663.656681 seconds after the previous acquisition. Safe-log publication/readback/backup completion and run completion follow it in order.
- Next six-hour eligibility is exactly **`2026-10-16T09:54:49.102563+00:00` / 18:54:49 JST**. All target acquisition/dispatch clocks remain on the exact intended JST date.

## Initial local verification stop

The summary records that the first new local verifier stopped before local restoration on an unwarranted `raw == sorted_canonical + newline` assertion. Independent byte comparison confirms the first difference at **zero-based byte 2**: the raw backup starts with insertion-order `date_jst`, while sorted canonical JSON starts with `active_venues`. The raw backup equals compact insertion-order UTF-8 JSON plus one final newline, and its complete exact SHA remains the expected 5c8d digest.

The current verifier's corrected line 31 requires a final newline and `len(raw) == len(canonical) + 1`; adjacent exact raw SHA and complete normalized API equality checks remain present. The retained facts therefore support correcting that unsupported key-order assertion, rather than altering source data or replaying acquisition. The exact original backup digest, artifact digest and current input stability all remain intact. The initial stop/no-repeat history is attributed to the recorded summary; this auditor did not execute or reconstruct an unrecorded earlier process.

## Scope and research gates

No actionable mismatch or evidence overclaim was found. Recorded research gates remain **UNVALIDATED / skip / []**, physical pairs zero and formal completion false. The summary's baseline count 274 and zero new predictions/exhibition/video are recorded context; the old 274 APIs or forecast archives were deliberately not reread. Disposed source originals were not recovered or their raw hashes recomputed. This audit establishes retained-byte/clock/program consistency, not a new source-accuracy, statistical, production-release or global no-other-run proof.
