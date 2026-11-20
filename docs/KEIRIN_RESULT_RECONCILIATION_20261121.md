# One scoped official-result reconciliation, 2026-11-21

## Authorization and limits

The owner explicitly requested completion of the remaining real collection
restart and production scoring, without bypassing access restrictions. The
earlier instruction also called for checking a legitimate acquisition route
before deciding whether a safety stop can be reconciled.

This change permits one reviewed attempt through the already approved public
KEIRIN.JP SP forms for the frozen race `202611208105`. It does not delete,
overwrite, expire or generally release the provider stop. It does not change
secrets, permissions, models, prediction originals, hosting, repository
protection, or any other source collector. Ordinary collectors still see the
same unresolved stop. There is no WINTICKET retry, `/pc/json` request, client
identity substitution, borrowed cookie, proxy, CAPTCHA solving or fallback
provider. A newly observed refusal immediately ends source work.

## Retained evidence and its limits

The actual state branch at review was
`a3a48900e8ee3f4c453c6d9c223b1b27598102c2`. Its only provider-stop record was:

| Field | Verified value |
| --- | --- |
| Path | `state/keirin/ab/provider-stop/v1/2026-11-20.json` |
| Git blob | `78983856f723be165b07aefc2aee951534ff1857` |
| Code | `PROVIDER_DENIED_OR_RATE_LIMITED_STOP` |
| Observed time | `2026-11-20T09:24:45.201674+00:00` |
| Run / job | `44710402748` / `136200450463`, `form-canary-settle` |

The [actual failed job](https://github.com/haji84/RACE-AI/actions/runs/44710402748/job/136200450463)
retained safe artifact `14617760267`, a 415-byte ZIP with digest
`00b753a3d497f90a934b0913e9632674d88c0f469ac5749e084c970c333485b3`.
Its only file, `summary.json`, reported
`HOLD_CANARY_PROVIDER_DENIED_PERSISTED_NO_RETRY`. Neither that report nor the
job log retained the failed host, HTTP status or rejected response. The
ephemeral private response files were removed by the normal cleanup step.

The separately retained normal Hofu payout guide, observed at
`2026-11-20T04:48:22.162216+00:00`, has SHA-256
`4ec68447b3883bee75065fb085e20825d4eacf377ae59f0b8bda8c9feb26ff64`.
The old broad challenge expression deterministically rejects its ordinary
Contact Form 7 reCAPTCHA scripts. The reviewed classifier accepts those
strictly recognized passive scripts while still rejecting actual challenges.
That is proof of a classifier defect, not proof that the later failed response
was this same guide. The historical incident remains unresolved.

Separate real WINTICKET jobs
[136180428323](https://github.com/haji84/RACE-AI/actions/runs/44704449231/job/136180428323)
and [136261471157](https://github.com/haji84/RACE-AI/actions/runs/44728334291/job/136261471157)
reported `DAILY_INDEX_HTTP_403`. Those refusals are not reconciled here.

The public-form route was already documented and used by the successful
capture/readback jobs of
[run 44679067367](https://github.com/haji84/RACE-AI/actions/runs/44679067367).
See `KEIRIN_FUTURE_FORM_CANARY_20261120.md` for source binding and the unchanged
four-arm acceptance conditions. A fresh HTTP 200 proves only the present
availability of the selected route; it cannot resolve the old incident or
prove an official result without parsing and origin verification.

## One-shot claim and runtime scope

`race_ai.keirin_provider_reconciliation.begin(repo, now, source_commit)` is a
keyword-only API. It requires all of the following before creating a claim:

- Trusted Actions repository `haji84/RACE-AI`, repository ID `1416489937`,
  `refs/heads/main`, `workflow_dispatch`, and run attempt `1`.
- Exact workflow reference
  `haji84/RACE-AI/.github/workflows/keirin-nationwide-ab-auto.yml@refs/heads/main`.
- The explicit workflow mode flag `CANARY_RECONCILE=true` and existing
  `RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED=true` opt-in.
- The real caller clock falls on 2026-11-21 JST. No caller clock is backdated
  to the original race day. The supplied source commit equals both
  `GITHUB_SHA` and the actual checkout HEAD.
- The exact original stop blob and canonical bytes remain present, with no
  other stop entry. Missing, changed, malformed or additional markers stop
  the attempt before provider access.

The claim lives separately from the original stop, at
`state/keirin/ab/provider-reconciliation/v1/202611208105/2026-11-21.claim.json`
on the existing encrypted-history branch. It contains only public runtime
identity, a public random attempt identifier, the reviewed stop blob,
timestamps and fixed source-purpose limits. It includes
`legacy_incident_resolved=false` and `general_source_release=false`.

The attempt identifier is not a secret or authentication key. Its purpose is
to prevent concurrent processes in the same run from constructing identical
Git commits and both treating an up-to-date push as a newly acquired claim.

There is one normal fast-forward push attempt. Only successful remote
readback of that exact commit/claim grants a process-local lease. No existing
claim can be reused, including after a crash, lost push acknowledgement,
readback failure, later dispatch or rerun. Any pre-existing reconciliation
namespace, including a malformed or orphaned entry, fails closed. Concurrent
losers obtain no lease and make no source request. The original stop and
prediction files remain unchanged.

## Lease and request boundary

The exported `ReconciliationLease` provides:

- `assert_active(now=..., repo=...)`
- `before_request(purpose=..., method=..., url=..., now=...)`
- `finish(state=..., now=...)`

The source lease lasts at most ten minutes from the claim clock and ends at
the close of 2026-11-21 JST if that is earlier. Request clocks cannot move
backward. Repository, run, workflow, code identity, remote claim and exact
sole legacy marker are rechecked before source permission is consumed.
The elapsed-time limit also covers the claim push and remote checks; a slow
Git operation cannot grant permission using an earlier caller timestamp.

Each purpose is consumed once, in this order, before invoking transport:

| Step | Purpose | Method | Exact existing host/path |
| --- | --- | --- | --- |
| 1 | `OFFICIAL_CALENDAR` | GET | `keirin.jp/sp/raceschedule` |
| 2 | `CALENDAR_SCRIPT` | GET | `keirin.jp/sp/static/js/SJ0201.js` |
| 3 | `FORM_SCRIPT` | GET | `keirin.jp/sp/static/js/commonSubmit.js` |
| 4 | `OFFICIAL_RACE_LIST` | POST | `keirin.jp/sp/racelist` |
| 5 | `RACE_LIST_VIEW_SCRIPT` | GET | `keirin.jp/sp/static/js/SJ0301_v.js` |
| 6 | `RACE_LIST_CONTROLLER_SCRIPT` | GET | `keirin.jp/sp/static/js/SJ0301_c.js` |
| 7 | `OFFICIAL_FINAL_RESULT` | POST | `keirin.jp/sp/race` |
| 8, optional | `OFFICIAL_PAYOUT_UNIT` | GET | `www.hofukeirin.jp/ticket/` |

Only the exact HTTPS URLs and methods are allowed; query strings, alternate
hosts, endpoints, identities and out-of-order/repeated requests are rejected.
An invalid request closes the lease. The existing collector still validates
freshly published form controls and opaque values, refuses redirects, checks
response status/content, persists actual denials and binds the result to the
frozen identities. The lease is not a substitute for those checks.

## Completion and preservation

The caller authenticates the frozen four-arm originals and their independent
GitHub origin evidence before calling `begin`. It uses the existing result
parser and scorer, then archives the authenticated result before declaring an
archived finish state. No new prediction is generated after the cutoff.

`finish` closes the lease first, then appends a safe receipt at
`state/keirin/ab/provider-reconciliation/v1/202611208105/2026-11-21.finish.json`.
Allowed states are `FAILED`, `ORDER_ONLY_ARCHIVED` and `FOUR_ARMS_ARCHIVED`.
The receipt records request counts and fixed purposes, not source bodies,
form values, cookies, private hashes, forecast tickets or payout values.
It is runtime accounting, not an independent official-result attestation.

A new refusal does not prevent retaining `FAILED` or a previously verified
`ORDER_ONLY_ARCHIVED` outcome. Finish persistence never authorizes a request.
Any failure leaves the original one-shot claim consumed. If payout-unit
evidence is unavailable or denied, a valid result order remains usable, while
unverified monetary scoring remains held. The unresolved original stop and
any newly observed stop remain in place after completion.

Nationwide rollout and actual operational acceptance continue to require
their own genuine evidence. Source-free tests and this reconciliation receipt
do not themselves prove success, accuracy or a general source-access release.
