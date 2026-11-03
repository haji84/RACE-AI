# KEIRIN result event to next-forecast handoff (research-only)

Implementation slice designed for existing Draft PR #72. The new `race_ai/keirin_result_reactor.py` (and synthetic tests) lives in a local patch pending repository write access.

The adapter accepts independently admitted FINAL_NORMAL result events, computes reference-only Hit@8, and prepares an idempotent private outbox intent for the next race only when verified pre-race snapshot, permission receipt, freeze readback and future official cutoff are all available. It never scrapes, issues provider permissions, runs a model, overwrites frozen forecasts, places wagers or claims official Hit@8. Missing authenticated provider feed, private queue worker and pre-cutoff receipts remain deployment blockers.

Related existing components: `race_ai/keirin_result_delivery.py`, `race_ai/evaluation_result_revision_bridge.py`, PR #71 `cutoff_job_queue.py`. GitHub actions and automatic provider polling are NOT enabled before explicit source-use authorization.

Official policy: https://keirin.jp/pc/dfw/portal/guest/policy/index.html
