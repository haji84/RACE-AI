# RACE AI verified checkpoint — 2026-10-15 JST

This is a resumable checkpoint, not a live dashboard. Read exact current GitHub/Vercel state before acting. Repository haji84/RACE-AI.

## Integrated main

Commit8bb7d69f9c8fb302055bc9e2609903d1e8f73e4b; tree293e81c2f88b6a0544dfea474b27a4b541b56414; README only. Initial open PR count50. PR46–59 Draft stacked. No integrated service, validated model accuracy or public release demonstrated. This proposed documentation branch does not change that.

## Changes made in this session

| Work | Exact evidence | Status |
|---|---|---|
| PR59 Preview repair | latest head610b90cd9667de60d75729e3137e4e1919d4cb1a; CI38611720204 success; immutable owner/repo-ID subject pinned | local/software repair verified |
| Preview Function startup | dpl_2PszR3s1rTDayutTPr8GodGk1TFP READY; authenticated GET probe405/AllowPOST, replacing old500 missing github_oidc | deployed startup verified |
| Actions protected POST + Blob | latest run38611712685/job116016956898:61bytes, SHA23a9b660…733fd72, BLOB_PROBE_VERIFIED, cleanup deleted | real normal roundtrip verified |
| Protection configuration | earlier narrow-rule API attempt404; latest exact-head Actions POST succeeded while SSO stayed enabled | connection works; do not repeat earlier failed configuration |
| PR60 Tokuyama worker | head efd12cac792cc7100387a1f4952db128d422e125; CI38608857764 success | Draft safe partial collector |
| Worker independent review | detached navigation date-proof defect reproduced and fixed with3RED→GREEN tests;20worker tests pass | code fix verified, live feed unverified |
| PR62 UI |head a6bc73d97d56e0f6626450e1883000763feb0643; CI38611271330 success;8references reviewed;7views;Chromium1440/390/320 synthetic flow passed | Draft software/browser verified, live/Safari unverified |
| PR63 Today SDK reader |head eee30c0af9ec0c2532eaab82943d7dc251d2d77f; CI38612150125 success including pinned-runtime stage;16focused tests after independent review fixes | Draft SDK contract verified, real I/O unverified |

## Integrated Preview checkpoint

Branch test/p0-integrated-preview ateb18b01e2e2149f99d47c3fb4260789a0759d9db; deployment dpl_Eqvs7BaMxSEbciGrPMwvZDHYAxKD READY. Authenticated /200, /ui-model.js200, /api/today503 FEED_NOT_APPROVED, /api/blob-probe405. Auth + Worker + UI + API suite208 tests OK,1existing OpenCV skip with pinned dependencies after integrating latest auth changes. Earlier snapshot used206 tests; it is historical. No combined-branch hosted CI is claimed; lane PR CI passed. See docs/evidence/20261015/INTEGRATION_CHECKPOINT.json and docs/P0_INITIAL_AUDIT_20261015.md.

## P0 not yet complete

Real private Blob put/get/SHA/delete is now evidenced in docs/evidence/20261015/LIVE_BLOB_PROOF.json. Complete live wrong-day/unapproved-feed negative E2E remains absent. /api/today on repaired Preview returns503 FEED_NOT_APPROVED. Preview BLOB_READ_WRITE_TOKEN metadata is bound to store_K4bSVFm5Bub7EdQf, and the separate owned probe-key I/O is verified; no real day-key feed I/O demonstrated. Ingestion/publication rights remain unknown. Single official10/14Tokuyama HTML audit parsed12races; this is historical index evidence, not today's full72boat feed. No actual iPhone Safari or full live display proof. UI fixtures are synthetic, not actual races.

SSO remains enabled for all deployments. Production remains dpl_5P4r39De9UGb1ZR5UXmDBzmop3Wb at d8c9ca88b5d20b58bdc9dcdeefba17718d43ca79 on feat/boat-first-mobile-release-shell. Production's unused RACE_AI_PROBE_SECRET metadata was audited without value access or deletion. No Production mutation or new paid resource.

## Resume

1. Refresh PR59/60 and subsequent UI/API PR heads, CI and Preview.
2. Preserve the now-working protected connection. Pin the observed immutable subject repo:haji84@173585154/RACE-AI@1416489937:environment:blob-e2e-preview. Earlier failed Trusted Sources API and older subject proposals are historical, not instructions to repeat.
3. Retain successful exact-head protected POST→private put/get→SHA→delete evidence. Finish live negative-feed cases and day-key storage proof once the publisher is connected.
4. Establish independently verified source rights; automatically acquire per-race details/time/meeting, reconcile registrations/motors, build allowed snapshot, then connect worker→Blob→SDK/API→UI.
5. Maintain corrected UI/API guards and completed synthetic/browser evidence; finish live E2E and actual Safari. UI session records are not persistent accounts.
6. Review existing dependency stack before main integration; final general release requires user decision.

GitHub Actions CI runs were observed. A continuously executing autonomous development scheduler has not been installed or demonstrated by this session.
