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
Historical probes are looked up using fixed repository/run/head/workflow/attempt/job/required-step contracts in trusted adapter code. Issuer and acceptance are derived from the public GitHub API, not imported PASS labels. Missing, failed, skipped, stale, future or mismatched observations remain blocked. Metadata facts are hashed; actual artifact contents are not downloaded by this adapter, and artifactContentVerified remains false.
The current PR execution head is checked before and after collection. Historical success never becomes current-product verification. The full product reminder remains blocked; assessCompletionPath executionAuthority is false.
API rate limits/network errors may block fresh verification; original canonical state is not overwritten with success. Runtime assessment is a derived report, not another durable source.

## Tests and operation
- node --test tests/race-compass-adapter.test.mjs
- node scripts/race-compass-adapter.mjs import docs/state/race-compass-state.json /tmp/race-compass.sqlite
- node scripts/race-compass-adapter.mjs export /tmp/race-compass.sqlite /tmp/roundtrip.json
- node scripts/race-compass-adapter.mjs assess docs/state/race-compass-state.json EXACT_CURRENT_PR_HEAD /tmp/assessment.json
The new workflow job must pass before claiming runtime integration verified. Deterministic tests include source pins, cross-project/schema rejection, stale/digest/revision/head rejection, failed/skipped/future evidence, unavailable evidence, real SQLite restart and preservation of over100 existing history/verification records.
