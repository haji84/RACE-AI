# Read-only proof for orphan rejection anchors

Existing Draft PR #42 is reused. Original metadata and ancestor proof are retained in docs/evidence/boat-pr42-preservation-20261118.json. No new PR, workflow job/input/cron/runner/timeout, release prefix or trigger marker is introduced.

## Observed problem

Main43 Actions diagnostics authenticated generation424 at 6eea8632c5d9a5504092c7b7c45ba57f3e7d6ddb. Rejection history has24 entries with missing ACTIVE anchors; observation600/history0 is consistent. BB completed24 physical rounds but emitted26 display rejections. Existing legacy result writers can clear active rejections while retaining their sidecars. Exact attribution of the bad commit remains unproved.

## Scope and sequence

1. Run invented tests first in the existing national audit unit job. Preserve existing guard and IO diagnostics, fixed M2 and BB-r0 steps, permissions, uploads and model/source authority.
2. Add a pure opaque snapshot-proof matcher. Require complete byte-equal older ACTIVE originals in the same parent race, parsed capture instant and source SHA, with valid reason-only history groups. Every orphan group must be proven; conflicting evidence or missing groups yields HOLD. Sidecars alone never authorize restoration. Inputs remain unchanged; no publication is implemented.
3. Add an Actions-only reader for two immutable selected snapshots: generation424 at6eea... and generation423 at71c1b06f36c4b6c01fcca6432c64ff5f4a18b8b9. Reuse pinned source86 F/H/bootstrap/decryptors and process-scoped Git authentication. The staging parent90d92... repeats the older manifest; it is not another generation. Authenticate manifest/cipher/header/AEAD/forecast anchor and contiguous previous-cipher links.
4. Use command-scoped filtered Git transport, bounded selected path reads, and read-only commit/push methods. Coverage is selected snapshot/day, never a whole-tree audit. Aggregate ciphertext-read bound256MiB and snapshot bound32 fail closed; these are forensic bounds, not a race discovery/GET cap.
5. Append one optional read-only safe-count step to the existing national main-push job using the existing trusted release prefix. Capture all private library output and report only fixed status/counts/public snapshot+cipher hashes and false effect/goal flags. Do not publish plaintext, source documents, URLs, names, records or exceptions.
6. Obtain independent review and actual CI, normally merge only the tested tree through the existing PR. Run the real private reader in Actions, preserve its safe output and update latest status. Finding proof is not restoration completion.
7. Separately fix recurrence using the smallest compatible display-only change after callgraph review, and only then implement a reviewed CAS restoration from independently authenticated older ACTIVE originals. Preserve all existing forecasts/results/observations/history, source budgets, clocks, model and production weights. No repair write is in the present read-only change.

## Acceptance and limits

The original bad synthetic input must still fail the unchanged guard before and after proof matching. Exact older ACTIVE proof and all-groups atomicity, no mutation/private output, malformed provenance and budget exhaustion are tested. Real authentication can run only on trusted main in the existing Actions key boundary. Job success alone proves neither healthy display publication nor all-day/all-model GOAL, physical iPhone acceptance, six-boat calibrated learning or prospective efficacy.
