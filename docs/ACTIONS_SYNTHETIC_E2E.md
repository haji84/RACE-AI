# Four-sport synthetic execution slice

Run with Python >=3.10 standard library:

```sh
python -m unittest discover -s tests -v
python -m race_ai.synthetic_e2e
```

Workflow: `.github/workflows/four-sport-synthetic.yml`, Ubuntu24.04 + Windows2022 standard GitHub-hosted runners, timeout5min/job. Pinned checkout with persisted credentials disabled; contents:read only, no Secrets/OIDC/source transport/deploy/artifact upload. No cron or autonomous operation claim. Public-repository standard runners are free per [GitHub billing documentation](https://docs.github.com/en/billing/concepts/product-billing/github-actions); no claim that other services/storage/old subscriptions are free.

The unit extracts the PR64 six-boat PL kernel, adds strict N-participant sport features, immutable original-first journal/results and replay. It is SYNTHETIC_ONLY, UNVALIDATED, NO_BET, with no economic process and no imported trainer. Scores normalize for algorithm tests; they are not calibrated real hit probabilities.

The demo discovers8synthetic races (2/sport), freezes4before synthetic sales cutoff, retains1missing-feature race,1nonoffered,1void,1pending. Nine result events include a correction. Three hits /5evaluable is synthetic arithmetic only; real race count is null. It reopens the journal and replays prior receipts. Tests additionally run concurrent processes, abrupt process exit, chain corruption/backup, old/current race revision corrections, deadline crossing, clock rollback and field tamper.

SQLite is a durable simulation on a runner, **not the production database**; no external trusted persistence timestamp is attested. Cross-run cloud restore, source collection, fitted models, real cutoff proof and ongoing PDCA/promotion remain future acceptance. A 2030 fixture clock never serves as current-day evidence.

## Cost and release boundary

Root and known web-root `vercel.json` disable Git deployments. [Official configuration](https://vercel.com/docs/project-configuration/git-configuration#git.deploymentenabled) documents this preventing automatic Git deployment; it does not cancel plans/storage or prove an actual account's invoice stopped. No Vercel/Cloudflare publish or billing action. No existing deployment/store deleted. No artifact upload/cron/minute fan-out beyond the small test matrix.

Before merge: confirm exact head/base and required CI; authorized independent reviewer/GORIQ gate; branch protection; inspect no Production auto-deploy and the exact Git config readback. A successful synthetic job or technical agent review alone never authorizes main merge. Then admit one real permitted collector/writer route with current rights, purpose, budget, real sales cutoff and external receipt; do not reuse old day/nonce/witness.

See [reuse audit](ASSET_REUSE_MATRIX.md), [conflict decisions](SPEC_CONFLICTS.md), [source gates](SOURCE_PERMISSION_MATRIX.md), and [completion evidence](ACTIONS_EXECUTION_STATE.json).
