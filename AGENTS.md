# RACE-AI: owner constraints

## Cloudflare is prohibited

The owner explicitly instructed on 2026-11-03: 「Cloudflare使わない！」.

- Do not adopt, deploy, provision, reactivate, call, or depend on Cloudflare for RACE-AI. This includes Workers, D1, KV, R2, Cron and the OIDC bridge.
- This instruction supersedes older documents, previous Cloudflare integrations, and suggestions in issues/PRs. A request to complete automation does not authorize changing this constraint.
- Do not re-enable `.github/workflows/keirin-d1-oidc-bridge.yml`, its live smoke test, key refresh, or D1 synchronization. Its jobs are disabled and automatic triggers removed.
- Existing Cloudflare source files are retained as inactive historical implementation, not an approved deployment path. Offline fixture tests do not authorize live calls.
- Administrative access is permitted only to stop the mistakenly introduced RACE-AI integrations or preserve/export existing data. Do not destroy D1 data or unrelated account resources without explicit permission.
- The dedicated `race-ai-keirin-private-state` workers.dev and preview endpoints were disabled and read back as disabled. The dedicated D1 remains untouched for data preservation; this is not migration completion.

## Preserve other owner constraints

- Vercel is also not an approved RACE-AI deployment target.
- Do not silently substitute another external service, enable new charges, expose prediction originals, change security permissions, or place bets.
- Reuse validated model, result-comparison, and local SQLite code where appropriate. Alternative hosting/storage selection requires a separate decision; do not invent an approved replacement.
- Preserve all pre-cutoff prediction originals and result revision history. Do not call an incomplete real-data automation pipeline complete.
- Prefer existing work/PRs. Main protection and required CI must remain intact. This narrowly scoped shutdown patch does not authorize merging unrelated draft work.
