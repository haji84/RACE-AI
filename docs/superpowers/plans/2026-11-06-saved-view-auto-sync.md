# Saved forecast automatic result sync

> Execution: root implements inline; fresh read-only final review. The owner's repeated instruction to proceed supplies the implementation/publishing authorization.

**Goal:** Automatically compare newly saved official results with the site's existing frozen forecasts and refresh results and budget simulations without reloading.

**Architecture:** The existing write-enabled GitHub result worker publishes only AES-GCM encrypted display projections to a dedicated fixed branch. Pages reads that GitHub raw feed every 60 seconds. An owner-recipient encrypted bootstrap delivers only the existing display key and pinned initial cipher to Actions; the root checkpoint key stays in Actions. No new service, permission, source request, worker frequency, or model execution is added by the publisher.

**Constraints:** GitHub only; preserve original forecasts, result revisions, canonical state, existing viewer URL, and active workers. Never publish plaintext data/keys/raw pages. The display publisher makes zero official GETs and never modifies collection policy. Display/reference comparisons remain separate from formal accuracy.

**Review focus:** Wrong recipient/purpose; concurrent feed writers; incompatible or newer pending observations; stale/tampered feed; draft amounts/settings overwritten by refresh.

### Task 1: Authenticated feed and immutable projection updates
- [x] RED: invented fixtures test recipient/purpose binding, unchanged forecasts, newer pending/revisions, raw-backed references, tampering and CAS.
- [x] GREEN: `race_ai/saved_view_feed.py` seals bootstrap, opens with existing root recipient, updates display only, retains cipher generations on fixed `state/boat-saved-view` branch.
- [x] Verify Python tests and commit.

### Task 2: Existing worker hook
- [x] RED: test already-fetched result handling and workflow hook without permission/cap changes.
- [x] GREEN: private raw cache outside uploaded artifacts; publisher after verified round, initial catch-up from verified existing result archive, no official HTTP in publisher.
- [x] Verify worker tests and commit.

### Task 3: Browser subscription
- [x] RED: browser sees two saved revisions; bad feed retains valid view; budgets/model choice/drafts preserved; no key in requests/storage.
- [x] GREEN: fixed-origin feed reader, authenticated generation header, 60-second non-overlapping polling, visible sync status; retain static fallback.
- [x] Verify existing viewer/financial/browser tests and commit.

### Task 4: Review and activate
- [x] Fresh review; fix important findings and verify full affected suites.
- [x] Preserve concurrent branch changes, publish reviewed static reader and encrypted bootstrap; do not launch another worker while active/queued.
- [x] Verify real Actions producer readback and existing owner link. Report actual scope and worker availability; do not claim indefinite scheduling or improved accuracy.

Deployment ruling: a concurrent upstream source worker was found active. Activate only the display job using a `saved-view:` head commit and independent concurrency group; exclude the official source job for that commit. The active old workflow is untouched. Upstream independently changed source limits to `None`; preserve that work, make zero official requests in this publisher, and make no claim that the source worker satisfies the earlier bounded policy. This feature's tests cover publication isolation, not approval of upstream collection policy.

Completion evidence: [saved-view-auto-sync-counts.json](../../evidence/2026-11-07/saved-view-auto-sync-counts.json). The subsequent upstream merge restored finite limits; no collection policy was overwritten by this feature. Review found display runs must also be excluded from supervisor/recovery discovery; authenticated push metadata now distinguishes them, including case-insensitive prefixes and pagination. Existing workers skip newer run IDs. All review findings were fixed with regression tests. Real Actions publication produced generations 1 and 2, source job skipped, existing source worker continued. Live browser verified 144 finals + 12 cancellations, 624 unchanged originals, 32 financial scenarios at mobile/desktop widths, and no display key in HTTP or storage. No deferred review findings.
