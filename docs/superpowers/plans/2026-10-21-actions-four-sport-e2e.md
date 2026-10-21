# Four-sport Actions E2E implementation plan

Goal: run credential-free synthetic discovery → odds-free Top8 → pre-sales-cutoff immutable freeze → official-result simulation/revision → Hit@8_all on standard GitHub-hosted runners.

Architecture: extract the already-tested six-boat PL calculation from PR64, adapt the same top-three formula to N participants, and add strict sport/snapshot contracts around it. SQLite is a synthetic durable-state test double; it is not the production database or an external timestamp witness.

Spec: Issue68 comment6315990805; PR61 fef68607b4773c59d6d46aa04b9e9762a42683d4 amendments and integrated instruction.

- [ ] Inventory exact main/PR59–65/KEIRIN PR1, reuse/dependencies/rights/conflicts.
- [ ] RED tests: four sports, market firewall/invariance, late/tampered freeze, corrections, missing forecasts, unknown rights.
- [ ] GREEN minimal adapters, append-only atomic journal, leases/idempotency, crash/restart/backup recovery.
- [ ] Independent technical review and fixes; this is not owner/GORIQ or GitHub APPROVED.
- [ ] Pin credential-free hosted CI; disable external Git builds in root and web configuration before push. No cron, artifacts, secrets, OIDC, source HTTP, production.
- [ ] Run exact-head hosted E2E, inspect job logs/summary, record fulfilled and blocked requirements.
- [ ] Real-data path requires fresh source permissions and externally witnessed durable storage; do not replay held PR64 POST.
- [ ] Main integration requires independent authorized review, branch protection and deployment/cost gate proof.

Original worktree/Cloudflare edits, PR64/65 heads, held33, old evidence and source pins remain untouched.
