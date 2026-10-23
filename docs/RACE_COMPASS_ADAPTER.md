# RACE Compass development checkpoint
Canonical durable state: docs/state/race-compass-state.json, versioned in this existing PR65 branch. It contains only technical project context and links, not full conversations, secrets or personal data. Its limited checkpoint criteria do not replace the full issue67 product specification.

## Real reuse, narrow boundary
The six vendor/compass source files are byte-identical to same-owner public haji84/AI- commit a500c70dd3585aeb83596f7d85cf7ee2975dbe2a. PIN.json records Git blob identities and the loader verifies bytes before importing actual CompassStore/assessCompletionPath. No upstream source is modified; no new framework or AI is introduced. Upstream repository currently declares no license metadata; this owner-requested reuse does not assert a new third-party license grant.
Node24 supplies native TypeScript stripping and SQLite. External Compass service/database access has not been established.

## Persistence and scope
The Git JSON is the sole durable source. A dedicated race-compass.sqlite is a derived working copy. The adapter imports only its namespaced gai-work-state envelope, preserving unrelated active records, owner receipts, history and verification rows. Export returns only this canonical envelope, not a claimed full export of every Compass database table.
Actions tests import, close the process, reopen SQLite in another process, export and compare against the committed JSON. This demonstrates actual existing Compass storage roundtrip if CI passes, not a permanently hosted database or automatic state writeback.
Only the existing authorized writer may publish updates using expected branch head CAS plus canonical snapshot hash/revision. The workflow has contents:read only, no automatic commit, API write, merge or deployment. No ChatGPT transcript backup capability is claimed.

## Evidence
Historical probes are looked up using fixed repository/run/head/workflow/attempt/job/required-step contracts in trusted adapter code. Issuer and acceptance are derived from the public GitHub API, not imported PASS labels. Missing, failed, skipped, future or mismatched observations remain blocked. Historical completion time is preserved; observedAt records the current successful API retrieval, never a fabricated new completion date. Old historical success does not verify current code. Metadata facts are hashed; actual artifact contents are not downloaded by this adapter, and artifactContentVerified remains false.
The current PR execution head is checked before and after collection. Historical success never becomes current-product verification. The full product reminder remains blocked; assessCompletionPath executionAuthority is false.
API rate limits/network errors produce an explicit BLOCKED historical-evidence report; original canonical state is not overwritten with success, and informational unavailability does not break unrelated future CI. Schema/provenance/current-head errors still fail closed. Runtime assessment is a derived report, not another durable source.

## Tests and operation
- node --test tests/race-compass-adapter.test.mjs
- node scripts/race-compass-adapter.mjs import docs/state/race-compass-state.json /tmp/race-compass.sqlite
- node scripts/race-compass-adapter.mjs export /tmp/race-compass.sqlite /tmp/roundtrip.json
- node scripts/race-compass-adapter.mjs assess docs/state/race-compass-state.json EXACT_CURRENT_PR_HEAD /tmp/assessment.json
The new workflow job must pass before claiming runtime integration verified. Canonical revisions after1 can bootstrap a fresh derived DB only through explicit trusted bootstrap; existing DB updates still enforce previous digest/revision CAS and preserve decisions. Deterministic tests include source pins, cross-project/schema rejection, stale/digest/revision/head rejection, failed/skipped/future evidence, unavailable evidence, real SQLite restart and preservation of over100 existing history/verification records.

## Verified bounded integration
At exact head4de53c4e1bb24210a53da628edb1935f0d5beb37, run39932267504/job120343186465 passed eight deterministic tests, actual Compass import -> separate-process reopen/export -> identical canonical JSON, and live metadata verification of all three historical probes with errors[] empty. The report remained BLOCKED/currentProductVerified:false/automaticWriteback:false. Full regression run39932267547 passed on both OSes (1141 Python,203 Node and8 Node tests each), using PR merge ref970bbac rather than the exact head checkout used by the adapter job.
Canonical revision2 records these observed results, latest observed PR71/72 contract evidence, unresolved full-product mapping and the next bounded integration action. It preserves the previous canonical digest. Later heads must run their own tests; historical success is not current-head or product completion.
