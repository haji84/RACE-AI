# GitHub-only encrypted SQLite handoff

Goal: retain the existing RACE-AI model and private SQLite state between GitHub-hosted runners without Cloudflare, Vercel or plaintext publication.

Approved direction: the owner explicitly selected GitHub after prohibiting Cloudflare. Implementation choice: the existing public repository and authenticated AES-256-GCM encrypted snapshots. A new private repository requires provisioning/access decisions; raw public SQLite is unacceptable. Neither is silently introduced.

1. Add bounded encryption using Node built-in crypto, authenticated repository/generation/history scope, private key checks, tamper detection, and create-only output. Local RED/GREEN tests.
2. Snapshot using SQLite backup API, not a raw WAL-file copy; verify integrity before encryption and after restoration.
3. Execute existing PR71 code on explicitly synthetic riders in one GitHub job; upload only encrypted SQLite and non-sensitive fixture metadata. Restore it in another runner and continue original-result audit plus next forecast.
4. A separate workflow_run consumer accepts only this repository's successful main producer, checks the original commit/run and retrieves only its named artifact. No secrets are given to PRs or the synthetic consumer.
5. Check production secret readiness on main by presence/validity only. No secret creation, logging or provider access. Update AGENTS.md with GitHub-only selection.

Review focus: AES-GCM key/tag/header failure, bounded files, symlinks/overwrite, WAL correctness, wrong producer or history, original forecast immutability, double counting, accidental plaintext publication and retention expiry.

Completion evidence is GitHub runner and cross-run handoff success on fictional data. Formal results, model improvement, real all-race operation, production key configuration and indefinite encrypted backup are not implied.
