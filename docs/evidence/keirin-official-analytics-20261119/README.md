# Official KEIRIN SP analytics request compatibility

Main `3c78b756960148f6bafd00a3dd243288430629ed`, Actions
[44547916659](https://github.com/haji84/RACE-AI/actions/runs/44547916659),
completed owner-source job `135643414848` reached the independent official SP
source: 37 HTTP 200 responses, no provider denial, one document and 36 resources.
The wrapper succeeded, but acquisition held with zero parsed calendars/lists/
details and seven requests blocked before transmission. This is not successful
race acquisition or a WINTICKET-side unblock.

An unchanged-guard local diagnostic reproduced exactly those counters. The first
blocked request was a same-origin, empty-body XHR GET to the public document's
inline-script-generated `/sp/ana`, without query, fragment or redirect. Its URL
SHA-256 is `43f0e1ed0f522c230efa1260a18708e7d8ec3514dbd995b348154a76d77e495f`.
Two earlier ordinary-browser requests with that same digest received HTTP 200.
The other six blocks happened only after the first stop was latched. This
identifies the collector's blanket XHR restriction as the immediate failure.

The diagnostic used installed Chromium 155 with ordinary Playwright defaults,
without changing transport guards, headers, cookies, network or user agent.
Its private diagnostic SHA-256 is
`a8b771de37133b344b6720f09d739f4439ab71fea3b96fc1a7fd698f2e3970c7`.
Raw documents, request details and source-derived values remain outside Git.
The completed Actions decoded-log SHA-256 is
`43fadefaf5e6d8f9648718b90d566d772db52b87d7b93dbebfe4eda1cb37c328`.

The fix inspects the exact analytics response regardless of MIME type across
accepted 2xx statuses, including challenge and size checks. It allows only the
exact published same-origin analytics GET and preserves
all status, denial, response, navigation and private-input gates. Unrelated XHR,
fetch, JSON API, other hosts, mutations, query/fragment variants, copied cookies
and synthetic browser identities are not introduced. A real later denial still
stops further navigation. All model admission and new-forecast counts remain
unchanged. The existing owner-cycle regression exercises this request together
with parsed invented race details, and originally failed at the same hold.

A genuine XMLHttpRequest in an entirely intercepted Chromium fixture also
exposed a lifecycle error: a received analytics HTML response could be queued
after the first DOM read, then read only after its page was closed. The collector
now drains those already-received resource bodies and checks the stop/budget
before closing their page. It does not suppress failures, omit denial responses
or turn unknown outcomes into zero. Three consecutive intercepted Chromium
flows then each verified one list, three details and 21 invented riders with 19
HTTP 200 responses, zero unknowns/blocks/denials and zero provider requests.

Final already-received bodies are also drained before cleanup. If an unread
body arrives during page closure, acquisition holds while retaining the actual
HTTP status and unknown-status counts. A fully intercepted final-page probe
reproduced the old false partial result and now holds; the unresolved control
still preserves one unknown status. No extra request or wait was added.

The original PR #102 head, metadata digest and all 120 original changed path
modes/blobs are preserved in `pr102-original-preservation.json`. Its immutable
source pin remains unchanged; preserving its ancestry does not activate its old
capture implementation or replay its tree. No new PR, service, schedule, model,
UI deployment, wager or weight switch is part of this correction.

Real acquisition after the fix must be checked separately. Neither a successful
CI wrapper nor fixture-based parsing establishes all-day, all-model coverage.
