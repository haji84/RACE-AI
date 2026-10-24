# Independent new-day-16 artifact audit

**Verdict: PASS. Actionable discrepancies: 0.**

Audit clock: `2026-10-15T15:48:14.404554+00:00` / `2026-10-16T00:48:14.404554+09:00`. Used Python standard library only (`pathlib`, `datetime`, `json`, `hashlib`, `zipfile`, `stat`, `zlib`, `re`, `unicodedata`). No product/helper import, existing restore-helper rerun, test run, source/network/storage request, Git operation, deletion, or subagent was performed. Only this report is written.

## Whole artifacts and both API bodies

| Saved artifact | Raw bytes | SHA-256 |
|---|---:|---|
| `artifacts/local/official-day-38761590081.zip` | 32591 | `c1c1c847c0585b5694da855b640d0a152b839648699a5e943687d2d209942fe6` |
| `artifacts/local/day-restored-38761590081/race-ai-day.json` | 349880 | `67c9f3d4782e0b2c3c02efe56d5bafa70591d02f3babe30242a4c9a77e0a95b2` |
| `artifacts/local/day16-api-functional-38761590081.json` | 380520 | `4f37b5c265c1093ca257944d2463c0049eb99d240d07cdab49a38ba58432945b` |
| `artifacts/local/day16-api-publisher-38761590081.json` | 380520 | `4f37b5c265c1093ca257944d2463c0049eb99d240d07cdab49a38ba58432945b` |
| `artifacts/local/day16-summary-38761590081.json` | 20708 | `1394dbdcca448b35a1adfefbd17a3861ab36ca3588edc7ed6ad1117b5ede9385` |
| `artifacts/local/day16-verified-log-38761590081.txt` | 749 | `195ed67db010d741f73bc908db4d804ee3e982a7a245ebda5bdbbd13980d2463` |
| `artifacts/local/day16-fresh-missing-proof.json` | 379 | `996f33b0e05a6207e5e599876f6c5ccd61cfcfe8a62b50cb653343bd4c0582a6` |
| `artifacts/local/day-missing-dispatch-20261016.json` | 1007 | `5389f70e7718098065bd044b422c622f82c1767be6a5f84bdfd5da3ed4491341` |

The ZIP contains exactly one ordinary unencrypted regular member `race-ai-day.json`. Its entire decompressed contents equal the 349,880-byte restored file, whose directory contains exactly that one file. ZIP metadata: uncompressed 349880 bytes, compressed 32445 bytes, CRC32 `adebeaaa`; CRC verification passes. All inspected files are regular and have no symlink/reparse flags.

Every JSON object, including embedded log JSON, was parsed with duplicate-key and nonfinite rejection. Independently canonicalized backup, functional-reader API body, and publisher API body are identical in full: **349,879 bytes**, SHA-256 `5dcddee8c61db1d1397805d19d559be66a12ce883c85528566f3a15d896e3923`. Their serialization is distinguished from raw bytes: the backup preserves insertion key order and exactly one terminal LF; the two saved API bodies have their own whitespace/order. Removing the backup LF alone does not produce sorted canonical JSON. No raw artifact was rewritten.

## Complete current-day coverage and identities

The complete objects have **24 distinct venues**, **13 active venues**, **156 distinct race IDs**, and **936 boats**. Each active venue includes exactly races 01 through 12; each race includes exactly lanes 1 through 6, six distinct four-digit registration IDs, and nonempty normalized names. Inactive venues are NO_EVENT with empty race arrays and complete dated schedule bindings.

| Active venue | Exact race-ID interval | Complete races | Boats |
|---|---|---:|---:|
| 01 | `20261016-01-01` through `20261016-01-12` | 12 | 72 |
| 02 | `20261016-02-01` through `20261016-02-12` | 12 | 72 |
| 03 | `20261016-03-01` through `20261016-03-12` | 12 | 72 |
| 04 | `20261016-04-01` through `20261016-04-12` | 12 | 72 |
| 08 | `20261016-08-01` through `20261016-08-12` | 12 | 72 |
| 09 | `20261016-09-01` through `20261016-09-12` | 12 | 72 |
| 10 | `20261016-10-01` through `20261016-10-12` | 12 | 72 |
| 13 | `20261016-13-01` through `20261016-13-12` | 12 | 72 |
| 14 | `20261016-14-01` through `20261016-14-12` | 12 | 72 |
| 19 | `20261016-19-01` through `20261016-19-12` | 12 | 72 |
| 20 | `20261016-20-01` through `20261016-20-12` | 12 | 72 |
| 21 | `20261016-21-01` through `20261016-21-12` | 12 | 72 |
| 24 | `20261016-24-01` through `20261016-24-12` | 12 | 72 |

All 156 program identities were independently reconstructed using race ID, UTC-microsecond close time, and lane-sorted `{lane, racer_registration_id, name}` rows with Unicode NFKC plus whitespace removal for names. Every independently computed program digest matches the corresponding summary entry. The entire sorted race-ID set matches the recorded future set. SHA-256 of the canonical sorted race-ID-to-program-digest map: `fcf8350d6ed5e134290ef9d2aeee27bd633a2ca7379e9e8cb334e1b7c3822e72`. Full canonical equality additionally covers every original program field across both API witnesses and the backup; no sample-only comparison was used.

Earliest close is `2026-10-15T23:35:00.000000+00:00` / `2026-10-16T08:35:00.000000+09:00`, race `20261016-14-01`. All 156 closes are on 16 October JST and later than both the root future-set check and this independent audit. This establishes timing of the saved B-program snapshot, not forecast creation or physical exhibition timing. Every race has `preview_available=false`; all boat display times and preview courses remain null.

All venue schedule clocks/URLs/hashes bind to the 16th day-index entry, and all race program clocks/URLs/hashes bind to the 16th B-archive entry. Top-level first/last source clocks and source references agree. Every non-null day-body clock is timezone-aware and belongs to 16 October JST. `upstream_published_at` remains null; unknown upstream availability is not invented.

## Missing-state witness, dispatch, and causal clock order

| Recorded event | UTC | Japan local |
|---|---|---|
| Dated missing-feed witness | 2026-10-15T15:34:45.000000+00:00 | 2026-10-16T00:34:45.000000+09:00 |
| Dispatch started | 2026-10-15T15:34:46.130377+00:00 | 2026-10-16T00:34:46.130377+09:00 |
| Dispatch accepted | 2026-10-15T15:34:52.567055+00:00 | 2026-10-16T00:34:52.567055+09:00 |
| Day-index observation | 2026-10-15T15:35:22.255185+00:00 | 2026-10-16T00:35:22.255185+09:00 |
| B archive / last acquisition | 2026-10-15T15:35:23.711762+00:00 | 2026-10-16T00:35:23.711762+09:00 |
| Pipeline verified | 2026-10-15T15:35:23.753635+00:00 | 2026-10-16T00:35:23.753635+09:00 |
| Publisher API verified | 2026-10-15T15:35:32.220274+00:00 | 2026-10-16T00:35:32.220274+09:00 |
| Runner backup restored | 2026-10-15T15:35:33.562350+00:00 | 2026-10-16T00:35:33.562350+09:00 |
| Root future-set checked | 2026-10-15T15:41:21.584934+00:00 | 2026-10-16T00:41:21.584934+09:00 |
| Independent audit | 2026-10-15T15:48:14.404554+00:00 | 2026-10-16T00:48:14.404554+09:00 |

The entire missing-state witness agrees in its standalone file, dispatch ledger, and summary. It records exactly HTTP **404**, `{error: FEED_NOT_SAVED, date_jst: 2026-10-16}`, before the same-day accepted dispatch. The recorded absence check preceded dispatch opening by 0:00:01.130377. The ledger identifies `CURRENT_DAY_TYPED_NOT_SAVED`, one accepted run, and `DO_NOT_REDISPATCH`; summary records `repeat_started=false`. This is the authorized new-day missing-state path, not a same-day six-hour refresh claim. A 404 is not independently treated here as general collection permission; authority comes from the owner-authorized operation described in the task.

Reader/absence-verifier pin: `7f600ea39600bcb67e18ad1bf205eb29de46f6c2`, recorded deployment `dpl_4rT5qEruFVB2Ljveet5e9nX74oNw`. Producer/publisher pin: `325ddce19ae999d626782a9929e6511c17d60ba1`. Workflow commit: `ff95b0f0dd7c273cad5bd589ca19e0a7d0b97e0a`; workflow blob: `2807d1981b99eddbf7cdf0b7cd8f24562a991bca`. These pins agree across supplied witnesses; the sanitized publisher log independently names the producer pin and correct version pathname for 16 October. The new reader is distinguished from the unchanged pinned producer; this audit did not update either or query deployment provenance remotely.

Run **38761590081**, job **116513988419**, artifact **11985428253** are recorded in the summary; run identity also agrees with the dispatch ledger. The three sanitized log records agree exactly with the feed counts, canonical digest/version pathname, original backup hash/size, and summary event clocks. API-body canonical equality verifies saved content; without saved HTTP headers/timestamps for both API files, it does not independently re-establish their response status, receipt time, or deployment commit. Those operational attributions remain root/log/summary witnesses.

## Scope and limitations

Recorded official-source scope is two requests: dated day index and B archive. The body has two source entries and maximum two requests; summary reports two actual source requests. This does not count shared Blob scratch, publication, or readback as official-source requests. No raw HTTP trace was supplied to independently recount remote calls.

Original source bodies were not retained. Recorded source SHA-256 and extracted-text SHA-256 values have consistent format/bindings, but cannot be independently recomputed against original downloaded source bytes in this audit. No new source-authenticity claim is made. The 16th version pathname is confirmed in the log; preservation of the prior 15th storage namespace is a summary claim, not a fresh storage listing or re-audit of earlier artifacts.

Summary guards remain physical exhibition phase false, UNVALIDATED, skip, empty recommendations, and formal completion false. The artifacts establish a complete current-day B-program snapshot, not physical-phase proof, new frozen forecasts, labels/results, accuracy, calibration, or model adoption. Full project completion remains false.
