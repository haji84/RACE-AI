# P0 one-race authorized 60-second upstream pilot (2026-10-24)

## Implemented in Draft PR #71, NOT DEPLOYED
- `workers/odds_auto_source_cron.mjs` + existing `workers/odds_feed_worker.mjs` scheduled handler (not triggered by repository CI).
- The upstream endpoint must be an independently approved *normalized JSON* full-120 provider, not unapproved HTML scraping of BOATRACE. Real rights, provider endpoint, request frequency, private retention, derivative full-odds display and source timing must be reviewed separately.
- Default disabled (`ODDS_AUTO_SOURCE_ENABLED` absent). Hard gates: existing Access requirement and ingest flag, reviewed rights flag/reference, one race identity, fixed cutoff, exact provider HTTPS hostname/source URL, verified full-120 schema, UTC durable attempt quota (max 10/day for this pilot), 60s atomic per-race lease, 403/429 backoff, D1 SHA readback.
- Schema `workers/odds_auto_source_schema.sql` is **not applied** to the private D1. No Cron schedule, secret, fee, website access, production authorization, public read permissions, or model/pick changes.
- Tests are synthetic normalized JSON with a fake D1 and injected fetcher. They test three distinct 61-second mock cycles, quote changes, deduplication and 429 backoff; they are **not real-source 60-second E2E**.
- The earlier real official source tests on 2026-10-24 prove only bounded manual captures and quote changes. Do not mislabel them as licensed automatic refresh.
- The owner-only deployed preview has browser read diagnostics, but a real iPhone Safari owner login, 120/120 UI read and three browser receipts are still awaiting the owner's device observation.

## Pending authorization and genuine acceptance gate
1. Get documented rights for automatic one-race per-minute acquisition, private D1 retention, display of all 120 quotations, and an approved normalized endpoint (or separately review a lawful alternate transport).
2. Check actual Cloudflare shared-account Workers, D1 and Browser Run remaining budget, especially other applications. Unknown means HOLD.
3. Before private staging schema migration inspect existing D1 schema/backups and get owner approval; do not overwrite or relax the existing preview config.
4. Only after approval, enable tightly pinned pilot flags/secret and `* * * * *` scheduled handler for ONE future race. Validate 3 actual 60-second source cycles with source publish, fetch start/end, D1 SHA readback and iPhone success receipts. Failed, unchanged and unavailable status must be reported truthfully.
5. Keep PR #71 Draft, no main merge, no general publication, no paid plan and no betting.

Sources: BOATRACE site policy https://www.boatrace.jp/owpc/pc/extra/policy.html , Cloudflare Cron https://developers.cloudflare.com/workers/configuration/cron-triggers/ .
