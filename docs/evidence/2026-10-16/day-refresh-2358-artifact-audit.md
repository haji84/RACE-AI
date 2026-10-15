# Independent 23:58 day-refresh artifact audit

**Verdict: PASS. Actionable discrepancies: 0.**

Independent audit time: `2026-10-15T15:10:10.906476+00:00` / `2026-10-16T00:10:10.906476+09:00`. This is a 16 October JST offline audit of the 15 October refresh. Used Python standard library only: `pathlib`, `datetime`, `json`, `hashlib`, `zipfile`, `stat`, `zlib`, `unicodedata`, `re`. No product modules/helpers or tests were imported or run.

## Artifacts and full-byte verification

| Local artifact | Bytes | SHA-256 |
|---|---:|---|
| `artifacts/local/official-day-38756184875.zip` | 32075 | `49c1897f683f4292bdbba89c728d4403d5e0ef369015c44e562b0157ead0a65b` |
| `artifacts/local/day-restored-38756184875/race-ai-day.json` | 349748 | `49de342e0d5c5aef9966483a45ca73aa9867f6e02ea0dde91999042a35abe198` |
| `artifacts/local/day-refresh-api-38756184875.json` | 380388 | `a3d5ed655b1457beab01517d0dbc58e25baffda8ed96d5cacc57149e22ce60b5` |
| `artifacts/local/day-refresh-api-38706348062.json` | 380384 | `f3e986673de62a963b7229f205e8f738fc365f40b60b106abb72adc7aa2c145c` |
| `artifacts/local/day-refresh-summary-38756184875.json` | 3185 | `b14e0dded7ee318fc7a64546e5fb95accb6aa0566486356434722106f3e376a7` |
| `artifacts/local/day-refresh-dispatch-20261015-2358.json` | 572 | `0beda758f700ab19fc893930b240d083a7844d9f04d8a36a83a6f2398ce1ada2` |
| `artifacts/local/day-refresh-verified-log-38756184875.txt` | 749 | `e238f7a2bc73a2220e4190ee0336b9adb78d399b811720afee2a67cde2e56eb3` |

The ZIP has exactly one ordinary unencrypted member, `race-ai-day.json`, whose full decompressed bytes equal the saved restoration. Its uncompressed size is 349748 bytes; compressed size 31929 bytes; CRC32 `2f75396d`. CRC verification passes. The restoration directory has exactly that file. Inspected artifacts are regular files without symlink/reparse metadata. All supplied JSON documents and log JSON are duplicate-key-free and finite; canonical reserialization also rejects overflowed nonfinite floats.

The backup is **349,748 bytes**, preserving original key order plus exactly one terminal LF. Independently sorted canonical JSON is **349,747 bytes**, SHA-256 `807e071172755b4a68d1e2b7efa39b5f2b3ef121f5d0d2003eae9bcb83282398`. The complete parsed API witness and complete parsed backup serialize to identical canonical bytes. The saved API witness itself is whitespace-expanded JSON (**380,388 bytes**), not literally the canonical serialization; its raw hash is listed above.

Removing the backup LF does **not** make its bytes equal sorted canonical JSON, because key order also differs. Insertion-order compact serialization reproduces the original bytes before the LF. The one-byte backup-versus-canonical length difference is the newline; key ordering is a separate byte difference. The API witness has its own whitespace/serialization overhead.

The root reports that an overly strict `raw == sorted_canonical + LF` assertion failed after the full restore. The independent diagnostics establish why and confirm the corrected full canonical object comparison. This audit also initially made an extra overly strict assertion that the raw saved API file was canonical; it stopped before any write. Read-only diagnostics showed the API witness serialization overhead, and only that offline comparison was corrected. No artifact was altered or reacquired. The root account and supplied ledger/summary state that acquisition, publication, download, and restore writes were not repeated; this audit performed none.

## Complete day and identity comparison

Both prior and refreshed saved day objects contain exactly **24 distinct venues**, **13 active venues**, **156 distinct races**, and **936 boats**. Each active venue contains all race numbers 1 through 12, and every race has six unique lanes, nonempty normalized names, and six distinct four-digit registration IDs. The other 11 venues contain no event and no races. All venue schedule and race program URL/hash/observed-clock bindings match their own dated source entries.

The independent identity object is `{race_id, closed_at, boats}`. Close time is normalized to UTC with six fractional digits. Boats are sorted by lane and include `{lane, racer_registration_id, name}`; names use Unicode NFKC then all-whitespace removal via `"".join(unicodedata.normalize("NFKC", name).split())`. All **156 complete normalized program identities**, covering **936 lane/registration/name triples**, are byte-identical to the previous saved API identity projection. This compared full objects rather than trusting reported hashes. SHA-256 of the independently generated canonical sorted race-ID-to-program-SHA256 map: `68fb91f6d05a995e52d3c3c4a712d1e7f3d08d8df1104e2327bfc39fc1d887d8`.

| Active venue | Races | Boats | Complete identities unchanged |
|---|---:|---:|---:|
| 02 | 12 | 72 | 12 / 12 |
| 04 | 12 | 72 | 12 / 12 |
| 06 | 12 | 72 | 12 / 12 |
| 10 | 12 | 72 | 12 / 12 |
| 11 | 12 | 72 | 12 / 12 |
| 12 | 12 | 72 | 12 / 12 |
| 13 | 12 | 72 | 12 / 12 |
| 14 | 12 | 72 | 12 / 12 |
| 15 | 12 | 72 | 12 / 12 |
| 20 | 12 | 72 | 12 / 12 |
| 21 | 12 | 72 | 12 / 12 |
| 22 | 12 | 72 | 12 / 12 |
| 24 | 12 | 72 | 12 / 12 |

Every race retains `preview_available=false`. All race closes are on 15 October JST and precede the late refresh source observation. No close time is substituted for actual observation/availability, and this late snapshot is not preclose evidence. Original parser strings are preserved in the raw artifacts; NFKC/whitespace normalization is used only in the comparison projection.

## Six-hour gate, clocks, and operational evidence

| Event | UTC | Japan local |
|---|---|---|
| Previous last acquisition | 2026-10-15T08:32:29.679228+00:00 | 2026-10-15T17:32:29.679228+09:00 |
| Dispatch ledger opened | 2026-10-15T14:58:19.224049+00:00 | 2026-10-15T23:58:19.224049+09:00 |
| Dispatch accepted | 2026-10-15T14:58:25.853936+00:00 | 2026-10-15T23:58:25.853936+09:00 |
| Day-index observation | 2026-10-15T14:58:46.518502+00:00 | 2026-10-15T23:58:46.518502+09:00 |
| B archive / last acquisition | 2026-10-15T14:58:47.179544+00:00 | 2026-10-15T23:58:47.179544+09:00 |
| Publisher API verified | 2026-10-15T14:58:54.424136+00:00 | 2026-10-15T23:58:54.424136+09:00 |
| Runner backup restored | 2026-10-15T14:58:55.660284+00:00 | 2026-10-15T23:58:55.660284+09:00 |
| Root body receipt upper bound | 2026-10-15T14:59:58.999999+00:00 | 2026-10-15T23:59:58.999999+09:00 |
| Midnight boundary | 2026-10-15T15:00:00.000000+00:00 | 2026-10-16T00:00:00.000000+09:00 |
| Root offline audit | 2026-10-15T15:04:05.800419+00:00 | 2026-10-16T00:04:05.800419+09:00 |
| Independent offline audit | 2026-10-15T15:10:10.906476+00:00 | 2026-10-16T00:10:10.906476+09:00 |

The previous last acquisition is independently read from the prior API body and agrees with the ledger/summary. Dispatch began **6:25:49.544821** later; the new last source acquisition was **6:26:17.500316** later. Both exceed six hours. Dispatch acceptance precedes both source observations. All non-null day/source/schedule/program clocks in both saved bodies are aware and on their proper Japan-local day; source, publisher, restore, and audit causality checks pass. No `available_at` is present in the day body and `upstream_published_at` is null, so unknown upstream availability/publication is not inferred.

The three sanitized log records agree with the complete body counts, canonical digest/version pathname, application pin, and original backup hash/size. Publisher verification and runner restoration occurred before midnight. The root receipt upper bound is a root/summary witness based on its reported body receipt before the 14:59:58 UTC clock observation; a saved JSON body alone cannot independently timestamp HTTP receipt. The root and independent audits are after midnight and do not backdate the acquisition or claim a day-16 API response.

Supplied operational references agree: run **38756184875**, job **116495126052**, artifact **11984296209**, application `325ddce19ae999d626782a9929e6511c17d60ba1`, workflow `ff95b0f0dd7c273cad5bd589ca19e0a7d0b97e0a`, workflow blob `2807d1981b99eddbf7cdf0b7cd8f24562a991bca`. Run/app/workflow are bound in ledger and summary; app is also in the publisher log. Job/artifact IDs and 14-day retention are summary metadata, not freshly queried remote state. The exclusive ledger records one accepted dispatch and says not to redispatch; summary reports `repeat_started=false`. This is execution-witness consistency, not an independent global remote-job-history audit.

## Scope and limits

Recorded official-source scope is **two GETs**: the dated day index and dated B archive. The body advertises maximum two requests and contains two source entries; summary records two actual official-source requests. Shared Blob scratch and normalized day publication/readback are separate operations. No retained HTTP request trace was supplied to independently recount remote calls.

Downloaded source originals are not retained. Recorded source and extracted-text SHA-256 strings have consistent syntax and bindings, but their original bytes cannot be rehashed here and source authenticity is not independently established. This audit verifies normalized retained artifacts and unchanged complete program identities. The summary claim that source/publisher code paths were unchanged was not independently checked against source code in this artifact-only scope.

This independent audit performed no fresh day-16 API/request, source access, collection, forecast generation, product CLI rerun, tests, browser/network activity, Git mutation, or subagent work. Subsequent live day-16 investigation by the root is outside this 15th-only artifact audit. No adoption, prospective accuracy, physical exhibition timing, or project completion is established. The full project remains incomplete (`formal_completion=false`). Only this evidence document and its parent directory if absent were written.
