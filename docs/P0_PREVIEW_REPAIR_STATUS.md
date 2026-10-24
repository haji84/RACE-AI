# P0 Preview repair evidence — 2026-10-15 JST

## Verified starting state

- main commit: 8bb7d69f9c8fb302055bc9e2609903d1e8f73e4b; tree: 293e81c2f88b6a0544dfea474b27a4b541b56414. README only. No AGENTS.md, PROJECT_STATE.md or ROADMAP.md found in fetched branches' history.
- 50 open PRs fetched. PR46–59 are Draft and stacked; none merged.
- PR59 head: 92b136c5407b40b3e95bbc62fdb673b67c7a18a9. Unit run38597262668 successful; source metadata run38597262866 successful. Neither is real Blob proof.
- Real E2E run38597251224, job115967041827: OIDC_TOKEN_ISSUED then HTTP403. It targets older deployment dpl_3h3W4mR3qr2ZgodaEagLQBds6Cto.
- Latest starting Preview dpl_G92Dzp5o2jAsEc2DpdHmb9mchXHD READY at PR59 head. Authenticated /api/today returns503 FEED_NOT_APPROVED.
- Authenticated older /api/blob-probe GET returns500 FUNCTION_INVOCATION_FAILED; runtime trace proves ModuleNotFoundError github_oidc. Original handler only emits404/200/503 for POST; original 403 is not an application handler response. Exact historical edge rejection reason is not recovered from the original response.
- Production dpl_5P4r39De9UGb1ZR5UXmDBzmop3Wb READY at d8c9ca88b5d20b58bdc9dcdeefba17718d43ca79, branch feat/boat-first-mobile-release-shell; not main. No Production change made.
- SSO remains enabled for all deployments. Preview-only BLOB_READ_WRITE_TOKEN metadata references store_K4bSVFm5Bub7EdQf; no actual store I/O verified. Production has an unused RACE_AI_PROBE_SECRET metadata entry; values were not read, rotated or deleted. Production cleanup remains separately gated.

## Local implementation and independent review

Repaired project-root import, accepted Trusted Sources OIDC header in addition to app Bearer, fixed branch alias with exact commit gate, bounded stale-deployment wait, no OIDC redirects, sanitized transport/parse errors, private Blob SHA plus cleanup, content-bytes and stream SDK results, pinned numeric identities/sub and pinned runtime requirements. SDK inspected: vercel0.11.6 get returns content bytes; earlier stream-only implementation was incompatible.

TDD reproductions failed before repair. Fresh full dependency run:172 tests OK, one pre-existing OpenCV skip. Dependency-free run skips three real JWT cases in addition; CI is updated to install pinned requirements and rerun them.

Independent agent auth_review executed real locally signed RSA JWTs, direct project-root import, ten local HTTP redirect checks, actual installed SDK dataclass, denial/commit gates and cleanup failure cases. No remaining local blocker found. This is an independent software check, not live GitHub/Vercel E2E or external audit certification.

## Unresolved external access

Official OpenAPI and Trusted Sources documentation were read. Narrow proposed rule: GitHub issuer, custom audience race-ai-preview-blob-probe, repository haji84/RACE-AI + numeric1416489937, owner173585154, exact feat/boat-oidc-probe-auth branch/workflow, blob-e2e-preview environment and subject; target preview only.

PATCH /v9/projects/prj_B6XEB1mdFUCmOlip8eUMeBvod5FR via Vercel connector returned404 not_found: Deployment Protection Trusted Sources not found. Request ID icn1:sfo1::z2thf-1791998998190-c90b2ab80fd5. No successful configuration change established. Re-read project confirms SSO still enabled. No bypass secret created or shared, no protection disabled, no Production access widened.

Next: diagnose/configure this exact rule through an authorized Vercel dashboard path, then run GitHub Actions against the repaired exact head and retain SHA/cleanup evidence. Connector-to-browser fallback requires user authorization under the browser tool's instructions. Automation Bypass is a documented alternative, but a project-wide secret is broader and GitHub secret write is not exposed by current tools; no unsafe code/URL secret fallback was used.

Actual Blob write/read/SHA/delete remains UNVERIFIED. /api/today real data remains blocked by source/publication permissions and storage wiring. Date-mismatch/unapproved unit rejection exists in prior suite; no live day feed proof is claimed.

Sources: GitHub PR59/actions URLs and Vercel runtime logs above; https://vercel.com/docs/security/deployment-protection/methods-to-bypass-deployment-protection/trusted-sources ; https://openapi.vercel.sh .
