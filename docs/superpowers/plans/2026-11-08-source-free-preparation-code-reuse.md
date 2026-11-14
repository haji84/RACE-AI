# Source-free preparation code reuse implementation plan

**Goal:** Remove an unnecessary whole-CI wait for a data-only issue child while
preserving every provider, owner-key and chronological source constraint.

**Approved design:** V2 preparation D may reuse source B's exact full first proof
only through direct sole-issue child C. B, C and D differ solely in the fixed
ISSUE and PREP JSON paths; all other tracked blobs and modes are identical. Actual
executed merge-workflow Git blob must equal B's tested workflow blob before key
access. B remains the exact authenticated closed attempt-two source. P1 and all
subsequent collect-head full-first requirements remain unchanged.

**Files:** existing `race_ai/all_existing_model_official_prepare.py`, existing
`scripts/all_existing_model_official_result_prepare.py`, and new focused tests.
No workflow, transport permissions, crypto, provider limits or public input edit.

- [x] Write failing V2 context, real Git topology/mode, merge-workflow and early-key tests.
- [x] Implement exact schema/context branch and bounded existing GET tree walk.
- [x] Preserve existing source evidence admission and exact three outputs; emit
      truthful V2 code-ancestor/issuer-parent/workflow evidence counts.
- [x] Run new tests, real fixture MAC/AES preparation, focused P1 regressions.
- [x] Obtain independent review; fix Important findings with regression tests;
      commit locally only and report SHA. No actual key/provider/GitHub mutation.

Review focus: extra tracked or mode changes, absent/duplicate/symlink data rows,
fork/actor/head drift, unrelated or malformed merge-workflow commits/trees, and
late source/PR changes must fail before key or before output as appropriate.

Verification: new8 tests including real fixture MAC/native/RESULT→P2 CLI→three
outputs passed26.025s; combined core/P1 eighteen passed43.636s. Final fast
new/P1/actions/workflow/transport forty passed0.484s; seven independently rerun
new fast tests passed0.370s. Independent review CLEAR. A synthetic Git test's
gitlink staging was corrected; no production change was needed. An interrupted
combined run's missing final output is not counted as a successful verification.
No real source, owner key, grant, workflow rerun or remote mutation was used.
