# Independent offline audit of the Marugame 7R result artifact

Verdict: **PASS for the offline evidence scope. No discrepancies found.**

Audit target: race `20261015-15-07`, result request `38726468766-1`, exact frozen forecast `38708771146-1`, application `325ddce19ae999d626782a9929e6511c17d60ba1`. Root reports workflow run `38726468766`, job `116393457858`, and artifact `11968143092`; their remote provenance is a separate root metadata gate, not an assertion established by local files.

## Method and inputs

Used Python standard-library JSON, hashlib, zipfile, datetime, Unicode normalization, itertools and math directly. No product verifier, score routine, or operational helper was imported or called. No tests, network, browser, official source, Git operation, or subagent was used. Only this report was written.

Read all six files in `artifacts/local/name-bound-result-restored-38726468766/`, the full `artifacts/local/name-bound-result-38726468766.zip`, and `artifacts/local/name-bound-result-summary-38726468766.json`. Trusted comparison inputs were `artifacts/local/name-bound-restored-38708771146/receipt.json` and `artifacts/local/day-refresh-api-38706348062.json`. The summary was cross-checked against derived values; it was not used as the source of truth for outcome, hashes, timestamps or scores.

Canonical JSON was independently serialized as UTF-8, sorted keys, compact separators, unescaped Unicode, and no non-finite numbers. Duplicate JSON object keys were rejected. The documented mathematical program/record hash field projections were supplied by root; they were implemented independently without executing product code.

## Full bytes and inventory

The ZIP has exactly six distinct allowed, non-directory members. Every member's uncompressed length and full bytes match the corresponding restored file. Every restored file is canonical JSON, is a regular non-symlink file, and is at most 256000 bytes. The directory contains no extra files. All five payload lengths/digests match the manifest; all six match the independently checked summary inventory.

| File | Bytes | SHA256 |
| --- | ---: | --- |
| program.json | 2164 | `9c70fea0087ebbabcc1ebef1fb99aeda091660beb1d43ff64115edc266602b2c` |
| forecast.json | 114084 | `ad1bbf97ae747ccf42488e5d1a85e430002fd94d0f706a344bf82ada9ec5f6bd` |
| request.json | 5617 | `dd9c19c4dd17388ebd4638ff4a8aad2cbd25539761dd4caefbff7766016ee9b0` |
| result.json | 5991 | `c861d42201798ee5e498f1e8f7ecd01d318826ad83d7c58201ed94b04574dc92` |
| evaluation.json | 2815 | `3ff42a19f39eecdde14dcf191921ab2045d2b0d9bf6aeb6f169b92c82927050a` |
| manifest.json | 977 | `94de6970dee13d9ceac1c165010201f7527c9a168b1de10fbd81a6f2650eb667` |

Total normalized bytes: **131648**. ZIP bytes: **28452**. ZIP SHA256: `ca374b6a3518381dcbdf085b8b08b2630812cbdcd1b0560d89df90dc4d41e13b`.

The manifest has the exact expected field set and literal integer types. It records COMPLETED, null failure reason, NAME_BOUND_RESULT_PUBLICATION, the exact race/forecast/result/app identities, **5 application GETs / 1 POST / 1 official request / 240-second bound**, and UNVALIDATED / skip / empty recommendations. This proves the retained counter assertions and their consistency with the artifact contract; actual transport counts and elapsed wall time require root's execution evidence.

## Own parents, labels and identity

The entire 114084-byte forecast equals the trusted old parent byte-for-byte, with SHA256 `ad1bbf97ae747ccf42488e5d1a85e430002fd94d0f706a344bf82ada9ec5f6bd`. Its own baseline is `38677457884-1`; its own name proof is `38703196877-1`. Program bytes exactly match the single target race in the retained approved, schedule-verified, 24-venue day feed.

Independently recomputed unsigned baseline, binding, input and forecast snapshot hashes; forecast/binding receipt hashes; baseline receipt, binding envelope and input links; the new result packet hash; result receipt hash; and all request/forecast/result finalization identities. Exact packet/request/receipt/final-marker field sets and literal schema versions match. Request snapshot and runner timestamp equal the result receipt values. The final marker links to the actual complete result receipt, and the forecast link resolves the unchanged full forecast and its own parents.

Recomputed identifiers:

- Original B program identity: `fe65cca37d02c66785ed802807dc0a0a638c2fecfcb65e02255ddd8d907498a7`.
- Full-name validation identity: `f725e935be5b9436a4d34078d34b3de1d4a4e8bb1dedbd92e0b2f111ea5b4597`.
- Parser record snapshot: `860d7731302fe5080cb43cf78df00a721fcf9de421f50239588f2b9c348171c0`.
- New label packet: `4a20da8730b7d3d1a6a74be7d8afd819a85694a3bb90d5db186d8c503aa5a7f2`.
- Result receipt: `6752bedfdd4944d5a50036f712ae4fa6fd5fff09fe7cdd9d431574c0f8ff12c7`.

Program identities use race ID, canonical UTC close, and lane-ordered registration/full-name tuples after NFKC and whitespace normalization. The B projection retains original B names; the validation projection uses each own binding's full name. They differ as expected. Record hashing excludes only snapshot_id, saved_at and storage_eligible_pre_race; parser-owned timestamp strings remain untouched.

All six result lanes occur exactly once. Each registration matches the B program, baseline and corresponding own name binding; every result full name strictly matches the corresponding verified full name after normalization. Lane 3 exercises the retained VERIFIED_B_ABBREVIATION relation. Observed finishes are unique integers 1 through 6:

| Lane | Registration | Finish |
| --- | --- | ---: |
| 1 | 4036 | 2 |
| 2 | 3557 | 1 |
| 3 | 3584 | 4 |
| 4 | 3448 | 3 |
| 5 | 5453 | 5 |
| 6 | 4027 | 6 |

Independently derived top3: **[2, 1, 4]**, equal to the record, report and summary. All row race IDs, capture strings and source URLs agree with the record. The declared source is exactly `https://www.boatrace.jp/owpc/pc/race/raceresult?rno=7&jcd=15&hd=20261015`. The record is AVAILABLE/raceresult/official_result, confirmed and settled, with no returned boats/refunds; both source/storage eligibility and cloud eligibility are false. Source SHA256 is retained as `840bb792c5104705de1fff69c3acf31021785f2656ec15e76fd0f6f3fb4309f3`; its agreement across the evidence is verified, but disposed raw HTML cannot be rehashed offline.

## Clock chain

Parsed aware timestamps independently. Every listed instant falls on **2026-10-15 JST**. The frozen forecast is confirmed before close. All subsequent parent/source/storage/generation/receipt/report instants are strictly increasing and postclose; canonical spelling is checked for newly authored label/receipt timestamps.

| Event | UTC |
| --- | --- |
| Frozen forecast confirmation | 08:52:50.687626 |
| Race close | 09:04:00.000000 |
| Parents retained/read | 11:19:34.810205 |
| Source capture | 11:19:38.778825 |
| SQLite memory save | 11:19:38.797799 |
| Label generation | 11:19:38.798608 |
| Runner save | 11:19:39.010073 |
| Cloud save | 11:19:44.948540 |
| Receipt confirmation | 11:19:45.665083 |
| Evaluation as_of | 11:19:58.584791 |

Program, parser record, packet and report close times represent the same instant despite their preserved spellings. The report's forecast and result proof clocks/identifiers/hashes match their full retained objects, and the summary's clock fields match the independently read values. Ordering of retained clock values is verified; local evidence alone cannot prove the physical time at which remote I/O occurred.

## Independent score arithmetic

Selected the baseline model by its frozen baseline_link.model_id and the two own forecast models. Verified report model IDs, versions, phase order and each model's forecast timestamps. For every model, the 120 combinations are exactly all ordered permutations of three distinct lanes from six, each probability is finite and positive, and their sum is 1 within absolute tolerance 1e-12.

Used the derived [2, 1, 4] outcome to select winner probability, independently summed all 120 squared probability/indicator errors per model (360 terms total), and calculated negative natural logarithm of winner probability. All nine derived metrics match the report within absolute tolerance 1e-12; the inspected values agree exactly.

| Frozen model | Winner probability | Multiclass Brier | Log loss |
| --- | ---: | ---: | ---: |
| official-program-rating-pl / 1 | 0.015931646301203212 | 0.9794557900275646 | 4.139447814436214 |
| name-bound-display / 2 | 0.017574419946130793 | 0.9770665599817572 | 4.041310846317648 |
| name-bound-original / 2 | 0.020516285367926268 | 0.9717730225453218 | 3.8865363000214233 |

The schema1 report is EVALUATED for exactly this one common race, with no exclusion. It retains physical_exhibition_timing_verified=false, research_only=true, UNVALIDATED, skip and empty purchase recommendations. These scores describe one retained label/forecast comparison and establish no physical precision, model adoption, video validation or purchase recommendation.

## Scope limits

This audit establishes normalized-byte integrity, consistency against the designated trusted local parent/day evidence, exact link/schema/hash identities, retained clock ordering and independent arithmetic. It does not independently establish GitHub run/job/artifact provenance, authenticated source origin, actual source request count, deployment/OIDC/trust state, real Blob write timing, complete live latest/pinned API equality, or protected UI behavior. Those remain root's job metadata and live verification gates. No source was reacquired, no old 4R workflow was repeated, and no remote mutation occurred.
