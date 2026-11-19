# KEIRIN A/B: production closure and actual evidence, 2026-11-19

## Outcome at candidate verification

The owner asked to finish the remaining work after reviewing PR #309. This
revision integrates the newer private owner view from PR #310, closes the
legacy runtime overlap and concurrent-writer readback bug, and adds a
source-free main Actions configuration check. It does not change Secrets,
repository variables, permissions, branch protection, hosting, or source-use
authorization.

Actual historical result verification has advanced from 1 to **17 races out
of the complete 79-race official 2026-11-18 cohort**. The remaining 62 are not
model losses. One additional older-format original, Seibuen 1R, has verified
pre-cutoff CI existence and authenticated decryption but lacks the matching
historical generator, so it is excluded from scoring.

These are different evidence categories:

| Evidence | Verified scope | What it does not establish |
| --- | --- | --- |
| Official JSON result | Utsunomiya 1R, 1 race | An autonomous nationwide day |
| Reviewed official venue PDFs | Utsunomiya 2–9R and Kochi 1–4R/6–9R, 16 races | An unattended PDF parser or first-publication timestamp |
| Historical encrypted originals | All 17 scored originals; exact crypto and original-model replay | Future model accuracy |
| Seibuen 1R older schema | Original CI server proof and RSA/AES authentication, A8/B8 | Full historical model replay or a scored result |
| Official refund announcements | 1 all-market cancellation, 1 market-scoped refund | Settlement E2E without matching prediction originals |
| Source-free configuration check | Implemented for trusted main only | Provider permission, successful source capture, or live acceptance |

## Runtime changes

The existing A/B selection is the conjunction of three existing opt-ins and
an empty legacy S3 prefix. Once selected, new legacy PR71 acquisition and
old-model generation, the old discovery/capture routes, and fallback dispatch
do not run. An unavailable official source does not silently select an old
collector. Partial opt-in retains the pre-existing route; no variable was
changed by this code revision.

Legacy ciphertext inspection remains available. Its reader runs after its
writer succeeds, or by explicit workflow dispatch while A/B is selected. It
is not added to every A/B poll.

The old writer previously rejected a successful save if another writer
appended before its readback fetch. Readback now requires the sent commit to
remain an ancestor and the exact `.enc`, `.scope.json`, and `.proof.json`
tree entries to remain unchanged at the observed commit. Changed ciphertext,
missing scope, rewritten history, and wrong blob modes still fail.

## Readiness on the actual main runner

`source-free-readiness` runs only after source-free tests pass, on relevant
main pushes or explicit `mode=readiness` dispatch. It verifies the repository,
repository ID, event/ref/run/SHA, actual checkout, existing owner RSA/SPKI pin,
canonical origin, and existing state branch through read-only `ls-remote`.
It prints fixed states, booleans and commit IDs. The private key is not passed
to Git subprocesses. Provider requests and state writes are zero.

Its success state is `CONFIGURATION_READY_LIVE_ACCEPTANCE_PENDING`, never a
claim of completed live capture. Actual main run evidence is recorded after
normal protected integration; candidate tests do not substitute for it.

## Historical replay and result provenance

Two original GitHub batches contain the additional 16 originals:

- [Run 44290470874](https://github.com/haji84/RACE-AI/actions/runs/44290470874),
  head `2f7ad8d2b9a0b40becf49dba01854b6cf86329e5`, 7 originals.
- [Run 44291507386](https://github.com/haji84/RACE-AI/actions/runs/44291507386),
  head `ff69cf8f90a4abc8bb80fe7c77fecc7f618457f5`, 9 originals.

Exact run/job/artifact identities, ZIP digests and members, original ciphertext
digests, separate runners and server timestamps are bound by the compatibility
verifier. No absent legacy counter is invented. Every accepted original has
at least 65 seconds between the conservative server evidence bound and its
actual official cutoff.

Both producer logs identify CPython 3.11.18. The fixed generator source SHA256
is `9aa0143192707733a9666f8d0dad70e589451f67943130796d3ed4af0387f413`.
The local Python 3.12 replay initially failed exact equality for 9 of 16
originals. Python documents the 3.12 float-summation change in its
[builtins reference](https://docs.python.org/3.12/library/functions.html#sum).
The isolated historical module reproduces 3.11's ordered accumulation without
changing current generator code or global builtins. All 16 then match the
original prediction digest and both complete authenticated arms exactly.

The official result PDFs were ordinary successful HTTPS responses:

- [Utsunomiya](https://utsunomiya-keirin.jp/data/racelist/racelist.pdf),
  SHA256 `426d73df32ac86ca63fc1472f7e6dfe4a5039adc481c56e2026d9227e8f67451`,
  observed 2026-11-19T03:23:40.475695Z, previous-day result table on page 4.
- [Kochi](https://www.kochi-keirin.jp/shussohyo/today.pdf),
  SHA256 `3433da2568abc9ecfea5f76ccd3f1f8c279691fa92e0222b4ed765e7e3322189`,
  observed 2026-11-19T03:25:19.661613Z, previous-day result table on page 1.

Two assistant visual reads agreed on all 16 triples and displayed payouts.
Kochi's embedded text also matched the image. All scheduled car numbers are
accounted for, including the literal disqualification in Kochi 4R. A missing
finisher or unknown withdrawal/refund status is not silently treated as a
normal result.

The PDF pages do not themselves state the 100-yen denomination. That basis
is separately supported by the official
[Hofu guide](https://www.hofukeirin.jp/ticket/) and
[Hiratsuka guide](https://www.shonanbank.com/beginner/). Their saved HTML is
retained with the private evidence. This is labeled external unit evidence,
not wording attributed to the two result PDFs.

The exact reviewed private record is pinned by SHA256
`9ba18bc253dd27910387e1d32bc7072a536ace7d9cf385d3359cb01340f5d6c9`.
Different PDFs or changed result transcriptions do not pass that pin.
`source_published_at` remains null: HTTP Last-Modified, PDF CreationDate and
retrieval time are not substituted for the first result publication time.

## Measured 17-race comparison

These are 100-yen-per-listed-ticket paper results, with no wagers placed.

| Metric | A | B |
| --- | ---: | ---: |
| Same verified races | 17 | 17 |
| First-ticket hits | 1 | 1 |
| Any-listed-ticket hits | 5 | 2 |
| Hypothetical total stake | 20,400 yen | 16,400 yen |
| Hypothetical payout | 27,170 yen | 2,080 yen |
| Exact payout/stake ratio | 2717/2040 | 26/205 |

The totals were independently recalculated from the authenticated original
tickets and checked results, apart from the shared scoring helper. The sample
is small and selected by available genuine evidence. It does not establish
predictive superiority or a future return.

## UI and independent review

PR #310's separate A/B/C columns, explanations and deadline-order tab are
included. C remains optional and evidence gated. An independent review found
that an OSError/RuntimeError from C verification could suppress valid A/B;
the external verifier now fails closed for C only. A regression reproduces
both errors and confirms A/B remains visible.

The same review caught duplicate original counting when an unverified
baseline race also appeared in a legacy batch. All baseline originals are now
included in the overlap guard. A negative replay using saved actual batch
bytes confirmed the duplicate is rejected. This did not affect the disjoint
17-race replay.

The private HTML has 79 unique races in each of the two order views, with one
79-race registration denominator. It has no external resource fetches or
scripts. Opening the full encrypted snapshot through the offline owner-view
CLI reproduces the same HTML. The full evidence was encrypted and decrypted
again with the existing owner key; source PDFs, private forecasts, keys and
raw result documents are not published in Git.

## Verification and remaining real-world gates

- Workflow source-free suite: 35 modules / **375 tests passed**.
- Current legacy runtime/workflow regression group: **91 tests passed**.
- Fixed PR71-source state/source-cycle group: **20 tests passed**.
- The groups overlap; these numbers are not added into a fictional unique total.
- Actual historical replay: **17 scored**, plus 1 explicit older-model HOLD.
- Actual refund-source reparse: **2 examples**, **0 settlement E2E**.
- Independent review: the two concrete defects above were reproduced, fixed,
  and rechecked. No further integration blocker was found in its reviewed scope.

A bare repository-wide unittest discovery is not a meaningful green gate in
this repository: workflows deliberately check out several pinned historical
source trees and run them in isolated import contexts. That exploratory run
failed; it is not represented as a successful full-repository test. Required
exact-head GitHub workflows remain the integration gate.

The permitted, complete nationwide live source route remains unestablished.
The observed KEIRIN.JP robots policy does not authorize the JSON route;
robots is not treated as a legal determination. No denial bypass or source
flag activation has been made. A future day's automatic complete intake,
pre-cutoff save, independent readback, result/refund settlement, stop and
resume still need actual receipts. Unknown partial-refund formats remain HOLD.

## Public safe receipts

- [17-race settlement](evidence/2026-11-19/keirin_17race_official_AB_settlement_safe_v1.json)
- [Refund source support](evidence/2026-11-19/keirin_refund_notice_source_support_safe_v1.json)
- [Seibuen original/model HOLD](evidence/2026-11-19/keirin_seibuen1r_original_model_hold_safe_v1.json)

The encrypted full evidence and updated owner HTML are retained as new
versions of the existing owner deliverables, preserving the previous revision.
