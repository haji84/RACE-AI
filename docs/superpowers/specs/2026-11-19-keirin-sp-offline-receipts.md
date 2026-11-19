# Offline KEIRIN SP receipts

Parse already captured calendar, race-list and race-detail HTML without network,
JavaScript execution, model inference or production admission. Preserve the
existing calendar parser at c0feb1b and its distinction between meeting ranges
and genuine race identities. No dependency, source pin or UI changes. Workflow
updates are limited to the existing push/PR path filters for the SP
parser/browser and their tests.

Both entry points receive bytes, an expected SHA-256, an aware observation
clock, and expected date/venue selection. Detail also receives an expected race
number. A required `calendar_receipt` has exactly `raw_bytes`,
`expected_sha256`, and `observed_at`: SP headers publish names rather than venue
codes, so the actual calendar header binds the expected code to the name. No
invented venue dictionary or relabelled PC JSON is accepted.

`parse_race_list` extracts the unique requested SJ0301 date group, validates
contiguous published race numbers and opaque read-only references, and returns
the existing saved-day-roster manifest shape. It never borrows clocks from the
initial SC0201 header, whose date may differ. A calendar range does not establish
national coverage.

`parse_race_detail` checks SC0201/SJ0315 against the selected calendar venue,
date and race, verifies official aftBetDate against BetTime, and treats StartTime
separately. Validate unique car numbers and six-digit official registrations.
Retain cancellation and entry notes; supplemental entry is not withdrawal.
Unknown notes cannot establish active eligibility. Preserve scores and other
statistics as source text, with no invented rates, denominators or strengths.

New detail receipts retain the published `kyakusitu` string as `style_raw`,
including whitespace, empty and unrecognized text. This does not classify a
model riding style or grant admission. Older V1 receipts may omit this additive
field; they and their original source bytes are not rewritten or backfilled.

Reject changed hashes, invalid clocks/types, ambiguous assignments, duplicate
JSON keys, nonfinite JSON, invalid UTF-8, incomplete HTML and bounded-resource
violations. Every result explicitly leaves source/model admission, full PR71
admission, full active eligibility and nationwide coverage false, with zero
model generations and provider requests. Returned source data is private; the
module never logs or stores it.

JSON-bearing inline scripts must belong to the document's head/body. Consume
their complete static grammar: comments, at most one global empty-object/array
`var jsonData` declaration before any data, literal first-level JSON assignments,
and literal scalar declarations for the fixed published routing variables.
Unknown statements, aliases, conditions, calls, mutations and namespace resets
are rejected. This recognizes data statements rather than interpreting JS.
Single-line comments end at CR, LF, line separator or paragraph separator.
Lexical whitespace follows the explicit JavaScript whitespace set; Python's
broader whitespace classification cannot consume non-JavaScript control bytes.

`http_status_verified` remains false: format validation cannot establish a
server response status or independently attest the caller's receive clock.
The caller retains the original capture receipt and private bytes.

Tests use invented public fixtures only. Real saved receipts are replayed only
outside Git, with safe aggregate evidence. This is offline parser completion,
not autonomous provider operation or a resolution of a provider 403.
