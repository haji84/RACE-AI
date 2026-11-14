# Supplemental BOAT observations — 2026-11-05

Existing Draft PR71 only. Official observations supplement the saved forecast view; they do not rewrite it or establish a model improvement.

- `source-index.json`: 11 actual official GETs, acquisition times and exact original hashes. Raw HTML/LZH and report text remain private.
- `entry-source-collection-proof.json`: real captured daily B/K files passed through the new collector, 129 normal races / 15 explicit exclusions; cache reuse caused zero additional requests. This was an offline real-input check, not a resumed live workflow.
- `actual-browser-summary.json`: Chromium 390/1440px, three real race contexts, source/comment/metric comparison, unchanged Top8, no writes or external browser requests. The six screenshots remain in the private capture folder.
- `automatic-browser-final-summary.json`: final actual app8765 automatic display, both widths and all three real contexts after validation fixes; no generation button, writes or external browser requests.
- `runtime-review-wait.json`: local app updated, 830 saved predictions; cancelled predecessor remains blocked from automatic restart.
- `original-preservation.json`: all 830 forecast objects and result histories match the authenticated saved projection; the native database hash remains unchanged.
- `verification.json`: final test counts, exact tested source hashes and review outcome (written after final verification).

The R06 exhibition sample was captured after its printed cutoff. Its six times/ST entries prove collection and display, not pre-cutoff availability or new forecast performance. R12 exhibition data was not published in the sampled captures. A weather label referring to R06 is retained as that label; it is not asserted to be fresh R12 weather.

The historical sample spans one day. Conditional finish rates describe observed configurations and carry their denominators. They do not establish a racer's intention, causal resistance, future entry order, calibrated race probability or a 98% Top8 hit rate. Zero-sample rates remain missing.

The existing collector now acquires the previous day's B/K sources, caches validated records, and restores the cache through the existing result/forecast artifacts. It uses the same source accounting and HTTP waits. The context-only SG fallback verifies roster and all printed schedule identities while returning no forecast outputs when the statistics layout is unsupported.

Automatic activation remains untested: the preceding workflow was externally cancelled and operator intent has not been confirmed. No trigger, rerun, new workflow or live source worker was started. Real Safari and video-based turn/exit/run-up/extension measurement remain unverified/unimplemented.

## Reproduction

Run `python -m unittest discover -s tests` and `node --test tests/*.test.mjs tests/*.test.cjs tests/ui_model.test.js` in the existing isolated checkout. The source collector uses only the already configured official-source authorization/guard; source-only pushes do not trigger the real forecast workflow.

Owner-private original captures are under `/workspace/owner-files/boat-context-20261105`; the CLI `python -m scripts.boat_context_import --help` imports those existing captures without fetching, inferring or modifying forecasts. The application reads supplemental records from `boat-context/` under its existing private roots. Private captures and projections must not be committed into this evidence directory.
