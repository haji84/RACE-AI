# Permissioned case submission intent plan

Goal: implement the missing consumed-intent and read-only uncertainty boundary
around an original committed case, using the existing writer and resolver.
Spec: docs/P0_PERMISSIONED_CASE_SUBMISSION_20261025.md. Base72b8c94.

Owner authorizes autonomous execution of the adopted design. Device/cost checks
stay in final acceptance; no new source, cloud mutation, paid service or main
authority follows. D separately criticized the design; C builds, root alone
integrates/pushes, A independently audits evidence. No CodeRabbit/self-approval.

1. C freezes exact API/callback/manifest handoff, then TDDs only
   race_ai/permissioned_case_submission.py and
   tests/test_permissioned_case_submission.py. Use one small prepared fictional
   case, actual original codec/model output and bounded recording transports.
2. D reviews concrete code and crash/concurrency/privacy counterexamples.
   Preserve RED failures, apply minimal repairs, retest and freeze exact bytes.
3. Root connects a small fictional CLI and the existing read-only CI workflow;
   independent review covers those changes. The unchanged actual writer runs
   only through recording fakes; no external writer or source I/O occurs.
4. Run new/full appropriate checks once after final repairs. Before ordinary FF
   to existing PR72 recheck exact remote HEAD, sole-writer lock, both old smoke
   refs manual-only and both Vercel automatic-deploy flags disabled.
5. Confirm exact-head CI, save private new-unit source/evidence packet, have A
   independently audit members/source/restoration/CRC/SHA/manifests, and update
   Issue68. Choose the next genuine real-input/external-retention dependency.

Done for this slice is verified implementation and fictional failure recovery,
not real submission, cloud persistence, all-sport E2E, formal approval or98%.
