# Local private whole-wire vault implementation plan

Goal/Done and the exact storage-only interface are frozen in
`docs/P0_LOCAL_PRIVATE_WIRE_VAULT_20261026.md`. Owner authorized autonomous
local-first development; actual device/cost acceptance is deferred. No real
destination or source authority is manufactured.

1. Root checks clean PR71 db075, original preservation and read-only inputs.
   D critiques this exact claim/schema/API boundary before product code.
2. C owns only two new modules, the real SQLite D1-shaped test adapter and
   focused Node tests. First preserve meaningful failing tests, implement the
   smallest bounded immutable byte primitive, then verify focused behavior.
   C never writes Git, workflow, existing source or the original dirty tree.
3. Root adds original V1/V2 wire integration without producer execution and
   the minimal Node24 CI paths/setup. Run meaningful local checks; preserve
   inherited Windows Python limitations rather than relabeling them.
4. D reviews final bytes independently; reproduce important issues and fix
   only concrete defects. A checks old assets and exact new source/evidence.
5. Only after final hashes/tests/review, root freshly checks both source-smoke
   manual-only refs and Vercel disabled, stages allowed paths and ordinary-FF
   pushes existing PR71 under the sole-writer CAS/lock. No main action.
6. Read the one automatic exact-head hosted CI to completion, back up all new
   source/evidence, restore/compare and independently audit. Record Issue68
   completion and next operational private-action dependency. Do not rerun
   completed prior evidence or claim real-data E2E/98%/cloud retention.
