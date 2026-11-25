# RACE-AI: owner constraints

## Detailed KEIRIN development requirements (owner instruction 2026-11-25)

- Continue against `docs/KEIRIN_DETAILED_DEVELOPMENT_SPEC_20261125.md` (the owner's 27 sections and six additional abilities). Read `docs/KEIRIN_DEVELOPMENT_ACCEPTANCE_20261125.md`, `docs/KEIRIN_JOINT_FORECAST_CONTINUATION_20261125.md` and existing Draft PR #327 first; preserve current work and avoid duplicate model/state/PDCA authorities.
- Keep implementation, retrospective studies, independent future validation and production acceptance distinct. Neither a correct finish nor a small-cohort gain proves correct race-flow prediction or nationwide accuracy improvement.
- Preserve the Seibuen conversation as reference unless its exact pre-cutoff original is restored. User observations, independently reviewed video, official records and AI estimates must remain distinguishable. Keep the published forecast asset as a separate, unchanged record.
- The GitHub-only, encrypted-original, source-access, permission-approval and protected-review constraints below remain in force. PR #327 remains an active research handoff; do not merge its unrelated work wholesale.

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
- Reuse validated model, result-comparison, and local SQLite code where appropriate. Do not invent an approved replacement platform beyond the owner's explicit choice below.
- Preserve all pre-cutoff prediction originals and result revision history. Do not call an incomplete real-data automation pipeline complete.
- Prefer existing work/PRs. Main protection and required CI must remain intact. Do not merge unrelated draft work.

## Owner selected GitHub-only continuation

The owner explicitly instructed after the Cloudflare shutdown: 「GitHubで出来るならそれで進めて」.

- Run on GitHub Actions and keep state within GitHub. Do not reintroduce Cloudflare, Vercel, or another hosting/storage provider.
- Keep RACE-AI public. Never upload plaintext private forecast SQLite files, keys, raw prediction originals or result-source documents to public branches, logs, artifacts or caches.
- The current implementation choice is authenticated AES-256-GCM encrypted SQLite snapshots. Production requires the owner's separately configured `RACE_AI_STATE_KEY` GitHub Actions secret, 32 random bytes encoded as base64. Do not invent a key from repo identifiers, GITHUB_TOKEN, a commit, OIDC or a public test value.
- Synthetic GitHub handoff tests may use the explicitly public fixture-only key with invented riders. They are not proof of private real-data operation, live accuracy, scheduled all-race coverage, or indefinite retention.
- A runner filesystem is temporary. Restore verified previous state before executing the existing model, and preserve the original prediction and revision history. Missing/expired state is a stop condition, not permission to reset the DB.
- GitHub artifacts expire. The three-day synthetic proof is not a permanent production backup. Indefinite encrypted retention and real-data feeder integration remain separate acceptance gates.
- No new private repository, unrelated project vault, changed repository visibility, paid runner or storage plan is authorized by the test implementation.

## Canonical KEIRIN development repository (owner decision 2026-11-10)

- The sole active KEIRIN prediction development repository is `haji84/RACE-AI`. Treat KEIRIN as one sport-specific module within the existing four-sport system. Keep prediction, source evidence, video learning, persistent state, results, and PDCA integrated here.
- `haji84/KEIRIN-AI` is legacy historical reference only. Do not start parallel development or duplicate schedules there. Its Draft PR #1 has old v0.4 docs; the promised v0.6 source was not observed in that repository's main. Preserve the repo, history, and open PR without forced merge, archiving, deletion, or rewriting.
- Reuse existing RACE-AI Issues #67/#68, existing Draft PRs #101/#102/#103, main workflows, source contracts, models, scorer, and SHA-bound source/archive paths. Create no second independent KEIRIN model authority or PDCA engine. Preserve existing work in progress before making changes.
- Do not automatically assume an old KEIRIN-AI design is fully migrated or compliant. If an actual missing historical asset is found, document its provenance and compare it against current RACE-AI contracts before a separately reviewed change.
- GORIQ (haji84/AI-) may orchestrate software development but is not another KEIRIN forecast repository. A GitHub Issue/comment does not prove GORIQ authenticated intake, a started WorkRun, or unattended execution.
- This is a reversible documentation / development-routing decision, not authorization to change secrets, permissions, vendor access, costs, repository visibility, branch protection, encryption, production deployment, or wagers. Existing Human Gates and required checks remain unchanged.
- Detailed inventory and real-race acceptance: `docs/KEIRIN_REPO_CONSOLIDATION_20261110.md`.

## Owner-approved Site import and matching inputs (2026-11-20)

- The owner supplied the existing `keirin-20261119-race-note.chankuma.chatgpt.site` and explicitly instructed: 「取り込んで、GitHubに取り込んで使える画面にして、入力元も同じようにして。」
- Reuse that owned Site's presentation, allocation functions, and preserved data formats inside this repository. Kdreams and netkeirin are approved input sources for this import, in addition to the prior WINTICKET/KEIRIN.JP paths. This explicit instruction supersedes the older two-provider restriction for this work.
- Keep the distinct sources and the original analysis, flexible revision and existing A/B research output identifiable. Do not turn these into an authenticated PR71 full-model forecast, invent C, overwrite original predictions, or promote weights.
- GitHub-only, encryption of private originals, no betting, no new charges and existing protected-review requirements still apply. The Site's Cloudflare Worker is not an approved new RACE-AI backend; port its needed functions to the existing GitHub path.
