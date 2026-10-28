# NAR local payback candidate intake (P0, 2026-10-23)

Reference: https://www.keiba.go.jp/pdf/manual/data_pdf_manual.pdf (payback list, page 9 of the 10-page PDF). The 2026 documented 54-column layout lists 3連単組番馬番1/2/3 at positions 50/51/52 and 3連単払戻金（円） at position 53 (1-indexed). Dead heats can cause multiple lines for one race, so multiple different 3連単 payouts are retained rather than overwritten.

\`python -m race_ai.nar_payback_adapter --input 20300101_payback.csv --output result-candidates.json --captured-at 2030-01-01T22:00:00+09:00 --source-rights-ref UNVERIFIED\`

The local CSV or ZIP has to be supplied in a permitted manner. No automatic downloading, copying third-party material into the public GitHub repository, odds ingestion, paid access or betting. Both headerless and explicitly matching 3-column header are supported, but unknown columns or date errors fail closed. The importer reads paybacks only after the fact; these are NEVER model features. It emits \`OFFLINE_UNVERIFIED\` with source SHA256, candidate winning triples, yen-per-100, and \`refund_status=UNKNOWN\`. No verified result, no official finality, no pre-cutoff evidence or score is inferred. No automatic settlement is granted by these untrusted local inputs.

Next integration acceptance: independently authenticate source rights for this use, source freshness and finality, the corresponding sale/refund rules, and an externally timestamped pre-cutoff prediction for the exact race. Use an immutable result revision ledger; calculate 1-point and 8-point performance only after all gates pass. No model updates from after-result information.
