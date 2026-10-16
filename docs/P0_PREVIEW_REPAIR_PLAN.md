# Preview probe repair plan — 2026-10-15

Goal: execute the user's P0 Blob proof while keeping SSO and Production intact.
Spec: user handover chapters 4, 29, 34, 48, 51–53. Ordinary fixes and Preview validation are authorized.

Observed baseline: main 8bb7d69f contains README only; PR59 head 92b136c5; unit CI passes; E2E run 38597251224 fails 403 after OIDC issuance. Its URL points at an older deployment. Authenticated GET then shows missing sibling import github_oidc; today returns FEED_NOT_APPROVED.

1. Add failing tests for Vercel-root import, trusted-source header, disabled redirects, exact deployment commit and Blob cleanup on success/failure.
2. Fix only scripts/run_private_blob_probe.py and web/api/blob-probe.py. Reuse the existing signed GitHub JWT verifier. Attach the same token to both application Bearer and x-vercel-trusted-oidc-idp-token.
3. Pin an existing branch Preview alias, require VERCEL_GIT_COMMIT_SHA == GITHUB_SHA, retry only deployment-not-current with a bounded wait; never follow redirects carrying credentials.
4. Add narrow official Trusted Sources rule for repository ID 1416489937, owner, branch, workflow, environment, custom audience; only target preview. Preserve all other access settings and SSO.
5. Probe private random keys, no day keys or user payload. Disable read cache, enforce bytes/SHA, delete exact owned key in finally, close client. Report SHA plus commit, never tokens.
6. Run whole suite with and without external JWT dependency, real signed JWT claim rejection tests, independent agent review, then update existing Draft PR59 with exact verified changes. No main merge or Production deployment.
7. Execute GitHub Actions real probe; record run/deployment IDs, SHA, cleanup. A blocked access path or rights gate remains unfinished, not successful.

Review focus: redirects cannot expose bearer; stale Preview cannot pass; failure cannot leave probe artifacts without detection; bad claims cannot enter; cleanup failure cannot be reported verified.
