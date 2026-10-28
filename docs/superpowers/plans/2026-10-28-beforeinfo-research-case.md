# Beforeinfo research-case implementation plan

Use the existing autonomous development authorization and independent review.
Spec: `docs/P1_BEFOREINFO_RESEARCH_CASE_20261028.md`.

1. Complete independent design criticism of the existing-asset reuse and input
   boundaries. Record exact findings and their resolution before implementation.
2. Record expected PR72 HEAD and exclusive allowed paths in Issue68. A owns only
   the new projector and unit tests; root owns spec, plan, taskboard and narrow
   offline CI wiring. Root alone commits and pushes.
3. Write meaningful failing fictional tests first, then implement the pure
   display-only projection. Existing parsers, models, profiles and journals stay
   unchanged. Preserve all original test failures and fixes separately.
4. Obtain independent code review and fix important findings; run focused and
   full reference-complete regression. Check original workspace/held records.
5. Fresh-check both source-smoke branches are manual-only and the target HEAD
   still matches. Commit/push once after local acceptance; observe the automatic
   exact-head Windows/Linux CI. No manual source workflow dispatch.
6. Independently review a bounded, source-free retained conversion caller. Root
   converts one already retained case once, with its own input/parent hashes
   and original context. Record the current conversion clock separately. Do not
   run a model, retrieve results or change any old forecast/journal.
7. Independently inspect actual conversion, archive/restore the new evidence,
   and record completed scope, limitations and next dependency in Issue68/PR72.

Completion means the verified projector and one actual retained conversion,
not new prospective predictions, full model coverage or formal product completion.
