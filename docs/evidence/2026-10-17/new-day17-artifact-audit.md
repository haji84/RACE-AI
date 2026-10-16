# Independent day17 artifact audit

Scope: only the new 2026-10-17 day publication, run **38925589162 / job117056187006 / artifact12056472531**, its ZIP/restored day, two retained APIs, summary and new operational evidence. **25 grouped checks passed; unresolved actionable findings: 0.** Only this private report was written. No network/source/API/media request, credentials, POST, job, helper/restore execution, test suite or old16/274 packet audit was performed. The audit scripts use only the Python standard library.

## Complete ZIP, backup and API content

ZIP **34,520 bytes / SHA256 `b64b3a711823ace5924c771aef0c77c8d3634815a554dae6ce23c74f451b29a1`** has exactly one safe unique member, `race-ai-day.json`. CRC, member size and every byte match the already-restored file. No encrypted, directory or symlink member is present.

The normalized day backup is **375,990 bytes / SHA256 `aea55271a49f50203cef9b0cd2513410b3cbd8346a46115baf029316b0ccbdad`**. It is compact JSON in its original key order with one final LF. Independently sorted canonical JSON is **375,989 bytes / SHA256 `8a368a5a2089452d99f40aa27d7dfad6fd6e16bb318d773b7731b0a8d7fe4e2c`**. Strict parsing rejects duplicate keys/nonfinite constants. Original backup and sorted canonical byte order differ; equality is not inferred solely from the one-byte length difference.

Reader and publisher API files are each **408,949 bytes / SHA256 `91ebba4835ef6f1fc8147f5099859e4e66b1368f77e7d603ce03db3c13781d4a`**, exactly equal to one another in raw bytes. Their complete parsed objects and canonical bytes match the restored day, including all venues/races/boats/source metadata. Their raw representation differs from the backup; no field-level sampling or parent-ID-only comparison was used. The summary's API lengths/hashes/full-content claims and transport-added-LF correction match these files.

## All new sources and programs

The day is exactly **2026-10-17**, provider `OFFICIAL_DAY_INDEX_AND_B_PROGRAM`, status `APPROVED_CURRENT_DAY_SNAPSHOT`, schedule_verified true and the existing publication review. It retains exactly two dated source records:

| Source | Observed UTC | Retained SHA256 |
|---|---|---|
| Official index `/owpc/pc/race/index?hd=20261017` | 2026-10-16 15:38:57.763361 | `113bdbab84049fa2bf7156b20a583ccfe84685489bb8df49e26eb61e252ef50a` |
| B archive `/od2/B/202610/b261017.lzh` | 2026-10-16 15:38:58.455905 | `792e96f390961d49f9671e53be2007e9c32e47a3782172ae5e8c919467e603a2` |

B source hash scope is explicitly **downloaded_archive**; extracted-text SHA is separately `8d4a7eac63d60aa295f347d30b2d7b41f5068c24f8beefcc5f0e0e5853212b5b`. Every venue's schedule URL/hash/time matches the index record. Every race's program URL/hash/time matches the B record. Top-level first/last acquisition times match those records. Raw HTML/LZH originals were disposed; this audit verified retained hash links and full normalized backup content, without rehashing disposed originals or inferring upstream publication timestamps.

All **24 venue codes01–24** occur exactly once:

- **14 READY:** 01,02,03,04,08,09,10,13,14,16,19,20,21,24. Each has exactly12 races, a nonempty meeting title and current_race_no1.
- **10 NO_EVENT:** 05,06,07,11,12,15,17,18,22,23. Each has zero races and the explicit complete-index nonlisting basis.

All **168 race IDs** exactly match date/venue/race-number1–12, with no duplicates. Every cutoff belongs to the new JST date. Every race has lanes1–6 and six unique four-digit registrations, giving **1,008 boat objects**. Names, grades, equipment identifiers and rate bounds are structurally valid; no registration crosses venues within this retained day. Grade counts by repeated boat object are **A1=217, A2=224, B1=488, B2=79**. These are B-program objects, not a count of distinct people or independently verified full names.

Every race's preview_available is false; average_st, display_time and preview_course remain null. No exhibition/physical-phase evidence is manufactured from program completeness.

All **168 program identity digests** were independently reconstructed from race/cutoff/six normalized identity tuples and match the summary exactly. Canonical SHA of the complete digest map is **`2c62b7754088a10e35c5fbb00098d7d28028b387af80a059b2217c30d280483f`**. The complete future-race identity list also matches. All168 scheduled cutoffs are future relative to the summary's recorded check **2026-10-17 00:42:06.946246 JST**; earliest **08:35**, latest **22:45**. These are retained schedule classifications at that time, not continuously refreshed event status.

## Actual acquisition clock and operational evidence

Last recorded real source acquisition is **2026-10-17 00:38:58.455905 JST**. Adding six hours independently gives **2026-10-17 06:38:58.455905 JST**. Summary/restoration/API record times were not substituted for this acquisition clock. The future boundary is an eligibility time, not evidence of another acquisition or scheduled execution.

Fresh exact dated404 captured **00:38:26 JST** matches the ledger and summary, with reader `fff20d27181cc1e01caac1d280eff5b1cce07d02`, fixed makwl83d8 Preview/deployment and integer404 body `FEED_NOT_SAVED / 2026-10-17`. Ledger start **00:38:27.236066**, accepted dispatch **00:38:34.348874**, first source **00:38:57.763361** and last source **00:38:58.455905 JST** are chronological. Witness-to-acceptance age is **8.348874 seconds**. The initial00:30 proof was not substituted for this fresh proof.

The own ledger still records `DISPATCH_OUTCOME_NOT_YET_KNOWN`, with the original fresh witness and exact lease/blob/publisher pins; acceptance is recorded separately. No token/header fields appear in it. Source-safe log artifact metadata independently matches ZIP digest, run, branch, lease and artifact ID. Its **completed/success job117056187006** is the final job-success evidence; `day17-source-run-initial.json` remains explicitly historical in_progress/null, attempt1. It is not used as final-success proof.

All safe-log records agree: fixed publisher325, bounded two-source collection,168 complete races,1008 boats,24 venue states, canonical version pathname/hash, complete backup bytes/hash and probe cleanup `deleted`. The summary's run/job/artifact, classifications, all168 identities/digests, lengths/hashes, clocks and research gates agree. Source/workflow counts describe the retained operation; reviewer request/job counters are zero.

## Exact new evidence identities

| File under artifacts/local | Bytes | SHA256 |
|---|---:|---|
| day17-summary-38925589162.json | 21784 | `5ffaf2352f1440d8b0784749e82cc34073edf5f60a29c3e3edc3357512391f66` |
| day17-source-safe-log.json | 2055 | `be114a377219ea9c0f020c7e632c0052d0b5a7ba326645c05d58e637efc3a82a` |
| day17-fresh-missing-proof.json | 379 | `a8776799a7a04164e6f59bd2b06d5211ffae21c76b7a773ca91c91ee975aeee0` |
| day-missing-dispatch-20261017.json | 813 | `69cf453a44018a5153ad707b6034cf284ef677101564cc99af4980675e5ec9ff` |
| day17-dispatch-accepted.json | 193 | `5c8aa5af163b3d5a07549fceaa580e5d0989aee0198311617b27aba0d17fd175` |
| day17-source-run-initial.json | 320 | `e52e4b715138ddf930c100681f458309e7fddb6f08a373aaeca40ea8d8e689cc` |
| day17-start-state.json | 1128 | `bf1dc606a5717322d8edbf89d70b03136fef89ce0737336cdea0bd932847ff12` |
| day17-missing-caller-review.md | 6027 | `4c4923541bc2f9c8a7db290cc7734499b3ed889cac3e9252adc27dda003b11a7` |
| dispatch-reviewed-missing-day17.py | 6536 | `c6bfcf167b6c047eaef688fd202e4dd6a517e3b28acd5ac13dc449afe44c45f3` |

## Preserved scope and final verdict

At the audit check, tracked HEAD is still **fff20d27181cc1e01caac1d280eff5b1cce07d02**, worktree clean, current COMPLETION/OPS whole-file bytes/hashes equal the day17 start-state record, and caller hash unchanged. Product/public records were not modified by this audit. Existing **274 historical baselines** are carried forward without advancement or re-audit. New17-day program168 does not mean168 saved forecasts; the new operation/summary records **zero new prediction posts**, physical phase false, UNVALIDATED/skip/[] and formal_completion false. No global cloud prediction inventory was fetched.

Old16 source data, prior274 packets, models, media, source jobs, restores and completed tests were neither reread for a historical audit nor rerun. No forecast calibration, full-name identity proof for every new B entry, physical timing or all-race forecast completion is certified by day collection.

**PASS0 — unresolved actionable findings: 0.**
