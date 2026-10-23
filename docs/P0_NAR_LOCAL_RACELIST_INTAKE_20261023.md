# NAR local CSV/ZIP race-list intake (P0)

Official document: https://www.keiba.go.jp/pdf/manual/data_pdf_manual.pdf . The documented racelist fields start with `競馬場`, `競走年月日`, `レース番号`, `発走時刻`. Only these identity/scheduled-start fields are read. Input file names follow `YYYYMMDD_racelist.csv` or `YYYYMM_racelist.csv` and may be inside one local ZIP. The importer requires a matching header and does **not** infer sales cutoff from scheduled start; no forecast can be proven with this file alone. It refuses unexpected ZIP layout, mixed dates, bad times, duplication, and unbounded data.

Run with an already-acquired local file where handling is permitted:
```
python -m race_ai.nar_racelist_adapter --input 20300101_racelist.csv --output fresh-audit.json --captured-at 2030-01-01T07:00:00+09:00 --source-rights-ref UNVERIFIED
```
These dates/venues in tests are fictional. The tool never downloads anything, does not parse the separate odds CSV or result/payback files, and never grants source rights. It emits `AUDIT_ONLY` with no forecast, no authenticated cutoff, no result, and no proven full-day discovery. Encoding supported: UTF-8-SIG and CP932. If a real official export lacks the header, this version deliberately rejects it instead of assuming a layout. User's genuine export file and provider-specific terms still need validation. No data are fetched or stored in the public repo.
