# Issue #67 P0: local real-data export intake boundary (2026-10-23)

Existing Draft PR #72 provides offline all-race coverage reconciliation. This change adds `race_ai/operator_export_intake.py` as an **offline normalized input adapter**, without touching models developed in PR #71, automatically contacting any provider, or using betting services.

Run: `python -m race_ai.operator_export_intake --input local-index.json --output new-audit.json`.

The input is an operator-supplied UTF-8 normalized race index, **not native provider ZIP or CSV parsing**. Required top-level properties are `schema=RACE_AI_OPERATOR_EXPORT_V1`, `event_date_jst`, `source_ref`, `source_rights_ref`, `captured_at`, `races`. Each entry has `sport` (boat, keirin, autorace, horse_jra, horse_local), `venue`, `race_no`, `sales_cutoff_at` (timezone offset or null), `offering_status` (UNKNOWN, TRIFECTA_REPORTED, NO_TRIFECTA_REPORTED). Entries with odds, popularity, results, predictions, or self-declared proof flags are rejected.

The resulting `RACE_AI_FORECAST_AUDIT_V1` artifact is **AUDIT_ONLY**. All races retain `prediction=null`, `cutoff_verified=false`, `result=null`, a missing-forecast reason, the source SHA-256 and the caller-claimed capture time. The output file is exclusive-created and cannot overwrite previous evidence. Missing sporting categories never mean there were no races. A matching manual reference does not prove official completeness. No private / licensed raw feed or personal information is added to the public repository.

Official-source reconnaissance:
- BOATRACE published nationwide official race-card/result download pointers: https://www.boatrace.jp/owpc/pc/extra/data/download.html ; policy https://www.boatrace.jp/owpc/pc/extra/policy.html .
- NAR documented race-list, entries, payouts and **separate odds** ZIP/CSV exports (https://www.keiba.go.jp/pdf/manual/data_pdf_manual.pdf); site terms: https://www.keiba.go.jp/terms.html .
- KEIRIN: https://keirin.jp/sp/dfw/portal/guest/policy/index.html .
- AUTORACE: https://autorace.jp/policy/ .
The existence of a public page/export is **not** a rights grant for repeated automated collection, storage, model training or republication. Permission evaluation for each intended use remains an independent required gate. JRA also needs separate verified terms.

Next gates: (1) independently establish exact source/method/cadence/reuse permissions (2) build rights-admitted *native* provider readers and pre-cutoff timestamped feature snapshots (3) prove 1 actual pre-cutoff immutable prediction anchored by the external GitHub server run and race/cutoff/hash read-back (4) settle official results incl. correction/refund/payouts (5) cover all four sports, daily scheduling, absence monitoring. These are **NOT COMPLETED** by this local adapter. No external source fetch, live forecast, receipt, main merge, deployment, payment, or auto betting is performed.
