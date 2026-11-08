# GitHub Actions migration: deterministic verification first (2026-11-08)

## Owner intent and boundaries

Reduce repeated ChatGPT/Codex agent usage by moving deterministic, unattended work to existing GitHub Actions. This change **does not** start real-race forecasting, authorize data access, change models, place bets, expose owner prediction originals, create a new service, or change production deployment.

The public `haji84/RACE-AI` repository is not approved to hold plaintext prediction originals, SQLite files or source documents. Keep the existing AES-256-GCM/key and restoration acceptance requirements in `AGENTS.md`. Never substitute an invented key. Cloudflare and Vercel remain disallowed.

## Phase 1: implemented by this draft PR

Extend the existing `.github/workflows/keirin-persistent-core-ci.yml`:

- Keep the original PR CI for core forecast/result/SQLite/discovery contracts.
- Add **one scheduled run per day at 06:37 JST** (21:37 UTC), plus manual `workflow_dispatch` on the default branch after merge.
- The scheduled core CI checks the immutable pre-cutoff/source contracts, result reactor, next forecast worker, local SQLite, synthetic model adapter and discovery.
- A **schedule/dispatch-only** extension runs the existing fictional-data tests for two-race SQLite restart/PDCA, owner runner, authenticated encrypted checkpoint, SQLite backup and Git-history archive. It is not added to regular PR runs.
- Limit the additional job to 10 minutes; keep read-only GitHub permissions and disable checkout credential persistence.
- Record the evaluated Git commit SHA and the scope in the GitHub Actions job summary. Do not upload state, secrets or forecast originals as artifacts.
- If contract tests fail, fail the job rather than report successful validation.

All tests here use repository fixtures. A green run proves those specific program contracts only. It is **not** a live, authorized, before-cutoff real-race forecast, an externally attested timestamp, national coverage proof, a real PDCA calculation, a model improvement, a betting result, or a forecast accuracy measurement.

## Existing work: do not reimplement or silently claim migrated

| Task | GitHub status visible on 2026-11-08 | Remaining gate |
| --- | --- | --- |
| KEIRIN limited roster discovery | `keirin-daily-discovery.yml` exists; scheduled and manual entrypoints | Independent coverage and permitted source/purpose verification |
| KEIRIN one-page canary | `keirin-personal-hourly-canary.yml` exists | Cannot substitute for all-race collection |
| KEIRIN encrypted state fixture | `keirin-github-state-proof.yml` / archive/restore workflows exist | Owner production key; real journal; immutable long-term retention; fail-closed restore |
| BOAT periodic result check | `boat-racer-daily.yml` exists, with a scheduled trigger and branch-pinned checkout | Verify exact runtime branch/rights/state and result reconciliation; do not infer full operation from YAML |
| AUTORACE/other four-sport model comparison | Separate feature-branch contracts/runs exist | Pre-cutoff model originals and independently sourced official results required |
| Habu PDCA bridge | `haji84/habuAI-private` has `pdca-command-poller.yml` | Protected raw inputs, qualified labels, valid trained model and owner acceptance |
| Habu box design validation | Canonical artifacts currently in ChatGPT Library | Define and independently verify canonical file/CI inputs before moving |

The `haji84/habuAI-private` repository currently reports GitHub visibility `public`. The name alone does not make it private. Do not upload confidential field data or raw GPX into Actions outputs or public repository content.

## Cutover acceptance

1. Review the draft PR, verify its precise diff and merge only after owner approval.
2. Observe a successful default-branch `schedule` or `workflow_dispatch` run and its actual checked-out commit SHA.
3. Confirm the test logs/summary contain **no private source data**, and record any failed or skipped contracts.
4. For any ChatGPT recurring task to be retired, first prove that an Action performs the **same scope and cadence** with persistent evidence and a clear failure path.
5. Keep all current ChatGPT tasks unchanged until step 4 is satisfied; no deletion or pause is authorized by this PR.

## Next migration gates

- Move repeatable *public/synthetic* reconciliation and per-model backtesting only after the required fixtures, rights and source identity are actually present.
- Use idempotent Actions with `concurrency`, bounded timeouts and explicit stop-on-missing-input states.
- Separate PR contract tests from real-data jobs; restrict access, keys and logs, and do not overwrite forecasts or result revisions.
- Preserve evidence per exact commit, run ID, source SHA and cutoff; prevent a synthetic green check from being called production success.
