# Official B minimal parser -> PR72 all-race audit, 2026-10-24

A direct GitHub-hosted **one-shot GET** from the authentic official B archive source succeeded for [2026-10-22](https://www1.mbrace.or.jp/od2/B/202610/b261022.lzh), archived hash `ec1f65cc04b2e4b04c01c5b952b7b88deb48391c6498f60e12de473e573e8200`, compressed size 32,775 bytes; the existing pinned PR64 LZH extractor decompressed 153,666 bytes in memory. PR64 `parse_b` successfully read **1008** six-lane entrant rows, which imply 168 races if every race is complete. The **strict** PR64 `program_details` parser failed with `B program detail layout malformed` before full fields/cutoffs could be validated. Source content was not retained or republished. GitHub [#40040401846](https://github.com/haji84/RACE-AI/actions/runs/40040401846) is a failed job, despite partial real-source successes: do not report strict B parser PASS.

`race_ai/official_b_minimal_identity.py` converts the output of a separately extracted/reviewed `parse_b` into the existing PR72 AUDIT_ONLY ledger after validating date, official B exact archive URL, unique six-lane registration IDs and true roster completeness. It deliberately emits **NO cutoff, no normalized features, no result, no prediction**. Raw boat and athlete data are not published by this adapter. The parser can be used on retained, legitimately acquired source bytes via a separately reviewed source contract; the actual Oct-22 download has already been discarded.

CI tests use synthetic PR64-shaped row dictionaries. Real source evidence in Actions establishes the *minimum* data path, not full data admission or successful automation. Separately fix the strict B detail layout based on an appropriately retained, legally usable provider fixture or carefully redacted format diagnostics; do not guess or make source-data available in the public repo. Then bind the full normalized feature source, authentic cutoff, and prospective forecast receipt without modifying PR71 research models.

Sources/policies: https://www.boatrace.jp/owpc/pc/extra/data/download.html and https://www.boatrace.jp/owpc/pc/extra/policy.html . Compliant continuous bulk acquisition conditions are not established.


## 2026-10-24 UPDATE: real source strict detail parsing is now accepted

The earlier failure reported above remains the historical outcome for PR64 at
`27f3df12ddca3971833d4dbf03f6fbcc88df6b07`, not the current outcome.

- A **single bounded** official B GET on a fresh GitHub-hosted audit run
  [#40049911334](https://github.com/haji84/RACE-AI/actions/runs/40049911334)
  for the same 2026-10-22 file returned HTTP 200. Compressed SHA256:
  `ec1f65cc04b2e4b04c01c5b952b7b88deb48391c6498f60e12de473e573e8200`.
  Archive byte size **32,775**, extracted text **153,666** bytes.
- The run was pinned to the corrected PR64 parser commit
  [`761247bee0209e37b1af6b8885e92cad3e9260a5`](https://github.com/haji84/RACE-AI/commit/761247bee0209e37b1af6b8885e92cad3e9260a5).
  It reports `REAL_OFFICIAL_B_FORMAT_ACCEPTED_AUDIT_ONLY`: **14 venues,
  168 unique races, 1,008 entrant records, 1,008 strict numeric detail rows,
  and 168 extracted *scheduled* sales cutoff strings**. Individual source
  rows and LZH bytes are not stored in the public repository.
- The actual mismatch on the earlier parser was its mandatory whitespace
  between fixed-precision decimal rate fields. The earlier redacted
  one-shot shape diagnostics counted **1,003** strict row matches and **5**
  mismatches despite all **168** headers and on-line cutoff formats matching.
  A more permissive, still two-decimal bounded delimiter between the first
  four rates resolved all five, with numeric range/identity guards preserved.
- These are **historical file-format verification and syntax acceptance**
  only. Official input *publication* timestamps, independent *live* cutoff
  authority, legally admitted retention/training rights, feature provenance
  and sample sizes, genuine pre-cutoff hash receipt, formal forecast,
  settlement/revision tracker, all-four-sport daily coverage, main integration,
  and Hit@8 remain unverified or unfinished. PR64 and PR72 are Draft PRs.
  No continuous polling, paid services, auto-betting, production publishing,
  or model/old-forecast changes were made in this fix.
