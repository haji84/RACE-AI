# PR72 to PR71: source race identity / research prediction binding, 2026-10-23

The implementation `race_ai/pr71_delivery_binding.py` joins a private model-delivery record in **existing PR #71** (`race_ai/permissioned_source_delivery.py`, `RACE_AI_PRIVATE_DELIVERY_V1`) to a previously observed **PR #72** Web/ZIP race discovery ledger (`RACE_AI_FORECAST_AUDIT_V1`).

This is an **offline compatibility bridge** between independently maintained Draft PRs. It does not copy model code into PR #72, issue official predictions, contact providers, train/update models, post a GitHub freeze, authenticate cutoff times, display unverified predictions on a website, or assert lawful collection.

Controls:
- Match `race_id`, `sport` (with horse_jra and horse_local mapped to PR71 model sport 'horse'), exact venue/event date, race number embedded in canonical identifier, and timetable versus model sales cutoff.
- Fail closed on duplicate discovery IDs, illegal outcome ticket combinations, 8-point violations, incomplete permutations and probability normalization, modified SHA256 of the delivery, snapshot, suite or model.
- **Review provenance remains separate**: a HMAC-signed record or a claimed `cutoff_verified` flag does not establish real rights, source authenticity, actual cutoff, independent evidence of GitHub storage time, or settlement.
- Accept research-only PR71 deliveries with `external_receipt=null`, `can_count_in_hit_at_8=false`, `official_prediction=false`. Keep these false in result. A source screen's announced cutoff is not an authenticated official deadline.
- Preserve the original complete daily AUDIT_ONLY ledger separately; do not erase unsent/missed races to inflate prospective hit rates.

After merger/review, separately attach a provider-authorized source normalized to PR71 full snapshot fields, *independently* authenticated cutoff, an append-only external GitHub-server receipt that **binds race_id, prediction SHA, cutoff, run event/head SHA and server time**, actual settled results/refunds and evidence for optional limited website projection. PR71's current `github_freeze_receipt.verify_github_freeze` checks cutoff and prediction hash but does not independently compare the pinned anchor race_id to the caller's race_id; that must be fixed in the final integration before production acceptance. Current RFC3161 timestamping is not implemented. Include this blocker in Issue #67.

As delivered, only a cross-branch **synthetic contract** runs with Python standard library and fictional racing input. Actual official source access / training is subject to separate legal/terms and access-method review. No new paid subscription, public deploy or wagering.
