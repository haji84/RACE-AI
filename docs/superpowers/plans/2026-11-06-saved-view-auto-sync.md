# Saved forecast automatic result sync

> Execution: root implements inline; fresh read-only final review. The owner's repeated instruction to proceed supplies the implementation/publishing authorization.

**Goal:** Automatically compare newly saved official results with the site's existing frozen forecasts and refresh results and budget simulations without reloading.

**Architecture:** The existing write-enabled GitHub result worker publishes only AES-GCM encrypted display projections to a dedicated fixed branch. Pages reads that GitHub raw feed every 60 seconds. An owner-recipient encrypted bootstrap delivers only the existing display key and pinned initial cipher to Actions; the root checkpoint key stays in Actions. No new service, permission, source request, worker frequency, or model execution is added by the publisher.

**Constraints:** GitHub only; preserve original forecasts, result revisions, canonical state, existing viewer URL, and active workers. Never publish plaintext data/keys/raw pages. Keep 240/session, 45/round, 24 rounds, 65 minutes, 180-second collection polling. Display/reference comparisons remain separate from formal accuracy.

**Review focus:** Wrong recipient/purpose; concurrent feed writers; incompatible or newer pending observations; stale/tampered feed; draft amounts/settings overwritten by refresh.

### Task 1: Authenticated feed and immutable projection updates
- [ ] RED: invented fixtures test recipient/purpose binding, unchanged forecasts, newer pending/revisions, raw-backed references, tampering and CAS.
- [ ] GREEN: `race_ai/saved_view_feed.py` seals bootstrap, opens with existing root recipient, updates display only, retains cipher generations on fixed `state/boat-saved-view` branch.
- [ ] Verify Python tests and commit.

### Task 2: Existing worker hook
- [ ] RED: test already-fetched result handling and workflow hook without permission/cap changes.
- [ ] GREEN: private raw cache outside uploaded artifacts; publisher after verified round, initial catch-up from verified existing result archive, no official HTTP in publisher.
- [ ] Verify worker tests and commit.

### Task 3: Browser subscription
- [ ] RED: browser sees two saved revisions; bad feed retains valid view; budgets/model choice/drafts preserved; no key in requests/storage.
- [ ] GREEN: fixed-origin feed reader, authenticated generation header, 60-second non-overlapping polling, visible sync status; retain static fallback.
- [ ] Verify existing viewer/financial/browser tests and commit.

### Task 4: Review and activate
- [ ] Fresh review; fix important findings and verify full affected suites.
- [ ] Preserve concurrent branch changes, publish reviewed static reader and encrypted bootstrap; do not launch another worker while active/queued.
- [ ] Verify real Actions producer readback and existing owner link. Report actual scope and worker availability; do not claim indefinite scheduling or improved accuracy.
