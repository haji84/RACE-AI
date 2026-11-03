# P0: One official-layout NAR daily race ZIP -> coverage + payout candidates

Source specification: https://www.keiba.go.jp/pdf/manual/data_pdf_manual.pdf
Provider terms: https://www.keiba.go.jp/terms.html

The official data-download manual describes YYYYMMDD_(UNIX timestamp)_race.zip with YYYYMMDD_racelist.csv (venues, dates, race numbers, scheduled starts), YYYYMMDD_horselist.csv (entry/runner info), and YYYYMMDD_payback.csv (settlement candidates). We read the bounded ZIP **offline, only if lawfully obtained**, and do NOT fetch it automatically. Odds ZIP/data is explicitly rejected.

\`python -m race_ai.nar_daily_bundle_audit --input /private/20300115_1894687200_race.zip --output /private/unique-nar-audit.json --captured-at 2030-01-15T07:00:00+09:00 --source-rights-ref UNVERIFIED\`

This creates a brand-new private local JSON report:
- A full audit-only ledger from race-list CSV.
- Optional separately isolated **unverified** 3連単 payout candidates; supports multiple dead-heat payout rows per race via \`nar_payback_adapter\`.
- Distinct lists of races without candidates and payouts whose race identifiers are absent from the race list.
- Archive and per-member SHA256 plus a caller-claimed capture time, not a server-authenticated timestamp.

\`horselist.csv\` is identified/hashed but NOT transformed to model features, avoiding guessed normalization and use-rights escalation. Scheduled start NEVER becomes official sales cutoff. Source rights, refund/revision conditions, official completeness, pre-cutoff immutable external receipt and actual prediction remain unproven. \`forecast_comparison_allowed=false\`, \`model_training_eligible=false\`. Never commit raw source data, private outputs or secrets to this public repo. No automatic betting or paid sources.

Test-only fictitious 2030 fixtures must never be reported as real coverage.

NEXT ACCEPTANCE (not yet fulfilled): authority-checked data source and bounded approved transport of exactly this ZIP; genuine current-day ZIP schema validation; independent official cutoff for a future race; normalized pre-race runners/features and older trained model; remote GitHub run/time receipt for exact race/hash; authenticated final result/refund revisions; four-sport daily coverage and monitoring. Keep P0 separated from model development in PR #71.
