# Offline SP parser implementation

Spec: `docs/superpowers/specs/2026-11-19-keirin-sp-offline-receipts.md`.
Baseline: c0feb1becb8ff70834b87d9a3f901b5c954bccc5, existing isolated worktree.

API: `parse_race_list(raw_bytes, *, expected_day, expected_venue_code,
observed_at, expected_sha256, calendar_receipt)` and
`parse_race_detail(raw_bytes, *, expected_day, expected_venue_code,
expected_race_number, observed_at, expected_sha256, calendar_receipt)`.
Observation clocks are aware `datetime` objects. SHA values bind original bytes.

- [x] Write invented-fixture tests for list/detail output, calendar binding,
  cancellation/notes, scores, malformed input and explicit admission holds.
- [x] Run the tests RED because the parser API does not exist.
- [x] Implement the bounded pure parser in
  `race_ai/keirin_official_sp_receipt.py`; run tests GREEN.
- [x] Replay actual private calendar/list/detail offline; verify aggregate
  counts, clock/hash agreement and preserved holds outside the repository.
- [x] Run existing calendar 10 and current-main official-source 32 fixtures,
  inspect the owned patch for source leakage, and commit local owned files.
- [x] Export baseline-to-candidate and owned-files-only current-main patches
  into private scratch for the parent's independent review.

Ruling: require calendar receipt context because SP detail has a venue name but
no numeric venue code. Caller expectations alone cannot prove that binding.
Ruling: run the explicitly scoped parser/calendar/official-source suites; the
task forbids broad redundant execution and does not change model/runtime code.
Review: the parent independently reviews the complete patch before any reuse;
no merge, push, provider retry or production hookup is part of this plan.

Execution ledger: 16 initial missing-API failures confirmed RED without test
errors; 20 parser tests GREEN after additional RED-to-GREEN cases for exponent
overflow, nested mutation, external script markers and detached HTML bodies.
Initial scoped suites: 20 parser + 10 calendar + 32 official-source fixtures pass.
Private replay: 14 aggregate checks pass, including existing manifest validation
and original clock/hash agreement. No real source data is included in Git.
Whole-patch independent review and any integration remain with the parent.

Independent review of df9ecaa reproduced three accepted invalid inputs RED:
compound/increment mutation, a cross-script namespace reset, and data after the
closed HTML document. The fix replaces mutation-pattern detection with complete
static statement consumption and document ancestry checks. Additional RED cases
cover alias/conditional statements and malformed routing-literal quotes. Fixed
scalar routing declarations match the actual private document shapes; no source
values were copied into fixtures. Revised scoped suites: 26 parser + 10 calendar
+ 32 official-source fixtures pass. Revised actual replay is byte-identical to
the original normalized private output. The initial commit, patches, review
block and nonpassing private DOM-audit assumption remain preserved separately.

The next review reproduced CR/LS/PS comment-termination failures and three
non-JavaScript control-whitespace inputs RED. The bounded lexical fix recognizes
all four JavaScript line terminators and uses an explicit whitespace set for
both comment skipping and statement grammar. Final scoped suites: 28 parser
+ 10 calendar + 32 official-source fixtures pass. Prior 6459af0 code, patches
and review evidence remain intact; no raw bytes or capture hashes are rewritten.
