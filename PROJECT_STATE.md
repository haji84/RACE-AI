# RACE AI verified checkpoint — 2026-10-15 JST

This is a resumable checkpoint, not a live dashboard. Read exact current GitHub/Vercel state before acting. Repository haji84/RACE-AI.

## Integrated main

Commit8bb7d69f9c8fb302055bc9e2609903d1e8f73e4b; tree293e81c2f88b6a0544dfea474b27a4b541b56414; README only. Initial open PR count50. PR46–59 Draft stacked. No integrated service, validated model accuracy or public release demonstrated. This proposed documentation branch does not change that.

## Changes made in this session

| Work | Exact evidence | Status |
|---|---|---|
| PR59 Preview repair | head cab804e72f314885166cf8e801814026ea38cfa6; CI38608293444 success, pinned signed-JWT stage passed | local/software repair verified |
| Preview Function startup | dpl_2PszR3s1rTDayutTPr8GodGk1TFP READY; authenticated GET probe405/AllowPOST, replacing old500 missing github_oidc | deployed startup verified |
| Actions protected POST | run38608285654/job116004737677:OIDC_TOKEN_ISSUED then HTTP302 | blocked before Function |
| Trusted Sources rule | narrow exact repo/IDs/branch/workflow/env/audience, preview only; API returned404 not_found | external access unresolved |
| PR60 Tokuyama worker | head efd12cac792cc7100387a1f4952db128d422e125; CI38608857764 success | Draft safe partial collector |
| Worker independent review | detached navigation date-proof defect reproduced and fixed with3RED→GREEN tests;20worker tests pass | code fix verified, live feed unverified |
| PR62 UI |head a6bc73d97d56e0f6626450e1883000763feb0643; CI38611271330 success;8references reviewed;7views;Chromium1440/390/320 synthetic flow passed | Draft software/browser verified, live/Safari unverified |
| PR63 Today SDK reader |head eee30c0af9ec0c2532eaab82943d7dc251d2d77f; CI38612150125 success including pinned-runtime stage;16focused tests after independent review fixes | Draft SDK contract verified, real I/O unverified |

## Integrated Preview checkpoint

Branch test/p0-integrated-preview at38da67ab487e25de926c80533352cdae52523691; deployment dpl_AnpKANCiAisYw3aYtMrnTabzkCbR READY. Authenticated /200, /ui-model.js200, /api/today503 FEED_NOT_APPROVED, /api/blob-probe405. Auth + Worker + UI + API suite206 tests OK,1existing OpenCV skip with pinned dependencies; bare stage206 tests OK,20dependency skips. No combined-branch hosted CI is claimed; lane PR CI passed. See docs/evidence/20261015/INTEGRATION_CHECKPOINT.json and docs/P0_INITIAL_AUDIT_20261015.md.

## P0 not yet complete

No real private Blob write/read/SHA/delete proof. /api/today on repaired Preview returns503 FEED_NOT_APPROVED. Preview BLOB_READ_WRITE_TOKEN metadata is bound to store_K4bSVFm5Bub7EdQf, but no live I/O demonstrated. Ingestion/publication rights remain unknown. Single official10/14Tokuyama HTML audit parsed12races; this is historical index evidence, not today's full72boat feed. No actual iPhone Safari or full live display proof. UI fixtures are synthetic, not actual races.

SSO remains enabled for all deployments. Production remains dpl_5P4r39De9UGb1ZR5UXmDBzmop3Wb at d8c9ca88b5d20b58bdc9dcdeefba17718d43ca79 on feat/boat-first-mobile-release-shell. Production's unused RACE_AI_PROBE_SECRET metadata was audited without value access or deletion. No Production mutation or new paid resource.

## Resume

1. Refresh PR59/60 and subsequent UI/API PR heads, CI and Preview.
2. Resolve Vercel Trusted Sources404 using an authorized dashboard path. Browser fallback authorization is needed under current tool connection instructions; do not disable SSO or expose bypass secrets. Config details: docs/P0_PREVIEW_REPAIR_STATUS.md on PR59 branch.
3. Run exact-head protected POST→private put/get→SHA→delete; save actual log and deployment IDs.
4. Establish independently verified source rights; automatically acquire per-race details/time/meeting, reconcile registrations/motors, build allowed snapshot, then connect worker→Blob→SDK/API→UI.
5. Maintain corrected UI/API guards and completed synthetic/browser evidence; finish live E2E and actual Safari. UI session records are not persistent accounts.
6. Review existing dependency stack before main integration; final general release requires user decision.

GitHub Actions CI runs were observed. A continuously executing autonomous development scheduler has not been installed or demonstrated by this session.
