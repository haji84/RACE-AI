# Actions-only KEIRIN plan preparation design

Status: parent approved for isolated implementation. No real public request,
source call, key access, capsule or remote mutation is part of implementation.

## Goal and constraints

Rebuild the lost private KEIRIN plan catalog inside the existing owner Actions
boundary. The configured `RACE_AI_STATE_KEY` secret stays on that runner. Produce
an encrypted plan, an existing recovery request and count/hash evidence for the
root to download and commit. Preparation does not issue a capability, call a
provider, fit a model, change a forecast, or write a PR/ref.

Reuse the existing `official_result_recovery_issuer` job, permissions and ten
minute timeout. Add no workflow, job, schedule, permission, local key fallback,
secret lookup/export, arbitrary source route or generic unknown exception.
Existing `official-results-issue:` behavior and writer remain unchanged.

## Approaches considered

1. Add a separate read-only preparation handler to the same job (recommended).
   Its authenticated input loading uses existing pure source/result/MAC readers;
   its output remains ordinary encrypted plan V1 plus existing S16/C/H requests.
2. Restore a private catalog on the local machine. This requires a local owner
   key and is excluded by the current environment and key-export constraint.
3. Extend the issuer itself to prepare and issue in one operation. This couples
   preparation to source authority and is unnecessary; preserve the current
   reviewed issuer-only path instead.

## Public preparation input and commit boundary

New fixed path: `audit/state/official-result-recovery-prepare-request.json`.
New explicit prefix: `official-results-prepare:`.
Schema: `RACE_AI_OFFICIAL_RESULT_PLAN_PREPARE_REQUEST_V1`.

Exact fields:

- `schema`, `repository_id=1416489937`, `workflow_id=392270247`, `pull_request=71`.
- `verified_parent`: exact `head_sha`, `run_id`, `run_attempt=1` and
  `first_viewer_job_id` of the preparation code's fully successful ordinary CI.
  It must be the sole direct parent of the preparation commit.
- `kind`: literal `KEIRIN_SINGLE_SIXTEEN_PROBE` or
  `KEIRIN_FIRST_EIGHT_AFTER_VERIFIED_SIXTEEN`.
- `target_event_day`: must equal the authenticated original plan's event day.
- `previous_source`: exact `head_sha`, `run_id`, `run_attempt=2`,
  `first_viewer_job_id`, `recovery_request_sha256`,
  `recovery_request_blob_sha256`, `journal_artifact`, `result_artifact`.
  Each artifact is the existing exact four-field pin.

Only this preparation JSON may change in the preparation commit. First land the
preparation implementation as an ordinary non-prepare-prefix code commit and
finish that exact HEAD's full attempt1 CI. Require the preparation commit's sole
parent to equal that verified code HEAD, with the exact full Python/video checks
and Viewer ID. Recheck the actual completed/success parent run before any owner
key lookup. This prevents newly added preparation code from seeing the owner key
before its own full CI has passed.

The proof always fetches the immutable attempt1. The parent's current run may
remain completed/success at attempt1, or be completed/success at attempt2 only
when that exact parent run/head is also the authenticated previous source. Reject
any other current attempt or an in-progress parent; do not copy the old issuer's
current==attempt1 guard into this separate preparation context.

Require owner PR71, same repository/feature/base branch and Actions attempt1 using
the existing trusted-environment/run-scope checks. Require the previous source
HEAD to be an ancestor and the current recovery request to remain byte-identical
to that actual source request. The latest topological public issue marker must
target this exact previous source run/head. This stops selection of an older
successful epoch while a newer issue/source epoch is uncertain.

The previous source run must currently be completed/success at attempt2. Fetch
its actual attempt1/jobs and require the complete Python and isolated-video
checks plus its exact Viewer ID. Preparation never uses its own first Viewer as
source authority and need not wait for its own heavyweight CI to finish.

## Authenticated evidence before preparation

Use fresh GitHub metadata and actual ZIP bytes through the existing read-only
transport. Validate exact pin/digest/size/run/head/repository/expiry; no fixture
or cached-metadata fallback. Fetch the immutable source recovery request at its
actual HEAD, check both requested hashes, and append the actual previous journal
and RESULT to every original cumulative pin. Retain the original four native
pins and authenticate all 177 native originals and every RESULT against their
frozen roster/race/cutoff/source evidence.

Use `I.check_pin_continuity`, `R._evidence`, `S._prior_evidence`,
`I.archival_authority`, existing native/result readers and `C.evidence`.
Authenticate the previous consumed capsule and join its authorization SHA to
the actual journal. All non-fixed prior outcomes must be known and non-DENIED;
the sole original fixed UNKNOWN remains actual-count null / upper-bound32.
Do not treat a new output directory, day or preparation as clearing it.

For initial KEIRIN16, the previous source is a genuine AUTO32 H3 continuation.
Replay its source plan/original S16 capability and all newly appended originals
as the private reviewed builder did. At least one newly authenticated normal
AUTO observation is required; this does not claim eight normal AUTO races.

For KEIRIN32, the previous source is a genuine KEIRIN S16 capability. Require its
original MAC/profile, complete wire, and exactly joined normal result before
building the existing C/H continuation. Its real frozen roster is retained
(normally7 or9 registered riders); never pad to8. Eight cases means eight races.

Calculate `earliest_issue_at` from the maximum of every actual prior run terminal
and journal server save (+1second), then +1hour. Preparation may return this
future time without waiting. The existing issuer still enforces that interval,
full first CI, same-HEAD fixed attempt2, actual-day midnight and minimum600 TTL.
Expired previous capabilities are archival evidence only, never live reuse.

## Derive unchanged plans; no private catalog dependency

Restore the exact original encrypted plan from its existing manifest/path/SHA
and owner AES key. Copy complete original case objects, original event day,
terms manifest, result-wait policy and the exact sport-filtered static-cache
list in original order. Never replay dynamic original responses or retime old
static entries. Existing authenticated runtime static-cache reuse stays separate.

- KEIRIN16: choose the first KEIRIN case in original plan order that the fixed
  old UNKNOWN entrusted to its browser (`DUE`/`HOLD_BROWSER_SOURCE_UNVERIFIED`).
  Set maximum_requests16; validate with existing `S._plans`.
- KEIRIN32: choose the first eight original KEIRIN cases on the original probe's
  normal UI route, in original plan order, including that probe case. Set32;
  validate with existing `C.validate_plan` and `C.evidence`.

Selection never uses winner, payout, likelihood or observed success. Missing or
ambiguous case/route or fewer than eight cases is HOLD. Require every selected
case to exist in the authenticated frozen-native union before marking ready.

Seal the existing plan V1 using `seal_forecasts` under the Actions owner key,
actual preparation run ID and a dedicated preparation-only envelope round
900033. This is an encryption namespace, not a source/collector capability.
The new cipher SHA determines its existing public plan path. Existing plan
loader validation remains unchanged.

For16 emit existing `S.REQUEST` / `S.HISTORICAL_MODE`, sport keirin, without any
continuation-only fields. For32 emit existing H3/C continuation and actual probe
pins/request SHA. Set manifest execution_day to actual preparation JST day;
target_event_day, original plan/native/label times stay unchanged. Late commit
or a changed execution day must HOLD in the existing runtime checks.

## Small code and job surface

- New `race_ai/all_existing_model_official_prepare.py`: literal preparation
  schema/context, evidence admission and deterministic plan/request builder.
- New `scripts/all_existing_model_official_result_prepare.py`: trusted Actions
  caller with read-only transport and delayed `state_key('production')` lookup.
- New focused tests for preparation/schema/evidence/output/privacy.
- The existing job's prefix router dispatches either its unchanged issuer step
  or the new preparation step. Preparation passes no writer/POST interface.
  Existing issuer proof/artifact names remain unchanged.

Preparation writes exactly three mode0600 files under a fresh runner-temp
directory: `sealedplan.enc`, `request.json`, `counts.json`. Upload only those exact
members as `official-result-recovery-preparation-RUN-1` with existing pinned
upload action and seven-day retention. Counts include ready/state, provenance
hashes, source run/head/pins, plan plaintext/cipher hashes, request hash,
case_count, maximum_requests, earliest_issue_at and fixed zero source/grant/
public-write flags. No raw source, roster IDs, original label, SQLite, key or
plaintext plan goes into artifact/log output. Failures emit bounded safe enums.

Root reads actual artifact metadata/digest and downloads the verified three-file
archive, then commits only the encrypted plan and returned public request through
normal Git/MCP. A new collect HEAD must pass its own full first CI. The unchanged
existing issue-only-child path then signs and readbacks the fresh fixed attempt2
capability; root separately checks proof/TTL and reruns only that source Viewer.

## Required tests after design approval

- Exact owner/PR/attempt/prefix/sole-file/ancestry/latest-marker checks; no runtime
  change in the preparation child, incomplete/unverified code parent, older
  successful source, in-progress/failed source or missing output.
- Real fixture MAC/AES and actual-ZIP-style native/result admission, all prior
  receipt/closure checks, DENIED and additional UNKNOWN rejection.
- Deterministic original-case/static ordering, frozen-native membership, no
  outcome-based selection, no invented cutoff/day/roster; exact7/9 KEIRIN labels.
- Source+capsule+result join, fresh metadata mismatch/expiry, lost original plan,
  tampered source request, changed terms/case/cache and insufficient cases HOLD.
- Ready artifact exactly three allowed files; no raw/key/plain-plan/output leak,
  no key lookup before admission, no writer/provider/model/dispatch call.
- Old issuer and workflow branch/proofs remain unchanged in behavior; source
  call counts remain0 under both positive and failing preparation fixtures.

No live key, provider, capsule, artifact publication or remote mutation is part
of the implementation validation. Actual preparation/KEIRIN results are pending.
