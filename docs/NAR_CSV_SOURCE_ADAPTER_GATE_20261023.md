# NAR official-format offline CSV adapters: pre-race and post-race separation

Status: **implementation/contract tests**, not admitted real NAR collection or a verified pre-cutoff forecast.
Owner goals: [Issue #67](https://github.com/haji84/RACE-AI/issues/67), [Issue #68](https://github.com/haji84/RACE-AI/issues/68).
Code is only on the Draft PR #71 branch; `main` is not integrated.

## Authoritative schema and legal boundaries

- NAR official [CSV download manual](https://www.keiba.go.jp/pdf/manual/data_pdf_manual.pdf), including the September 2026 FAQ update:
  - `YYYYMMDD_racelist.csv`: **66 columns**, race IDs/venue/race date and **scheduled START time** in columns 1–4; surface/direction/distance in columns 22–24. Columns **34–66** include actual post-race splits/corner passage and must not enter forecast snapshots.
  - `YYYYMMDD_horselist.csv`: **36 columns**, basic pre-race identities/numbers and historical summary; columns **32–36** include current-race finish, time, margin, final 3F and popularity, and must not enter forecast snapshots.
  - `YYYYMMDD_payback.csv`: **54 columns**, trifecta combination columns 50–52 and payout in column 53; **separate post-race branch only**.
  - Race ZIP contains race list, horse list and possibly payback; odds are offered as a **separate ZIP**. The CLI reads only the two required CSV members; it does not parse or expose payback/odds in pre-race outputs.
  - Official manual FAQ: **NAR does not provide stable IDs for horses/jockeys/trainers in these CSVs**. This prevents reliable cross-day entity joining without an independently lawful and verified identity mapping. A horse name is NOT a stable horse ID.
  - Download filename timestamps and operator-entered `observed_at` are **not proof** of prior server publication or actual storage time.
- NAR [terms](https://www.keiba.go.jp/terms.html) and [FAQ](https://www.keiba.go.jp/qa.html): unlicensed reproduction is restricted, and commercial reuse/modified republication is restricted. The existence of a ZIP button or format documentation does **not establish permission** to run an automated historical database, use it for ML training or republish snapshots. Source/purpose review is required. No license is claimed for this implementation.

## Implemented intake without scraping

- `race_ai/nar_official_csv_adapter.py`: takes a **separately operator-supplied** file pair and a verified `PermissionPolicy` instance. Explicit UTF-8 BOM or CP932 decoding and header mode, exact 66/36 columns, bounded bytes/rows, stable race-day/venue/R matching, duplicate number checking, start-time check, per-purpose signed rights reviewer gate, post-race field rejection. Outputs a **private pre-model staging record** with source SHA and declared vs observed entrants.
- `race_ai/nar_csv_cli.py`: offline operator CLI accepts an NAR race ZIP containing `YYYYMMDD_racelist.csv` and `YYYYMMDD_horselist.csv`, or two extracted CSVs. ZIP member/size/duplicate/path checks; no payback/odds transfer to the model. Creates an exclusive **mode 0600 private file outside Git** using the existing source-delivery safety writer. No automatic network request.
- `race_ai/nar_official_payback_adapter.py`: **post-race-only** separate 54-column reader. Preserves a reported 3連単 result, payout and multiple win combinations from dead heats without modifying the forecast. It does **not** mark results authenticated or add them to Hit@8 without separate official-source validation and append-only revision history.
- Tests: `tests/test_nar_official_csv_adapter.py`, `tests/test_nar_csv_cli.py`, `tests/test_nar_official_payback_adapter.py` are synthetic, fictional and non-networked.

### Explicit blocking / missing features

The NAR pre-race staging output has:
- `sales_cutoff_at=null`. **Scheduled start is NOT the official bet-sales cutoff.**
- `model_ready=false`, `forecast_frozen=false`, `eligible_hit_at_8=false`.
- `horse_stable_id=null`: requires a separate authorized stable-ID bridge.
- `missing_model_required_features`: the current four-sport model requires ability, recent form, speed figures, sectional strength, distance/surface, environment, etc. An official-format NAR CSV pair alone cannot be promoted directly to the model using fictitious normalizations.
- If entrant count differs from official racelist, status `HORSE_COUNT_MISMATCH_OR_SCRATCH_UNVERIFIED`; **no fake horses/scratches**.
- If any current-race result/popularity or race sectionals appear in the selected race's file snapshot, it is **rejected** for pre-race forecasting. Same-day already completed other races are not silently mixed into the selected race's forecast.

## Operator CLI after a *genuine* permission review

A real permission-scope record must first be reviewed/approved separately. See [signed policy contract](./P0_SOURCE_TO_MODEL_DELIVERY_20261023.md) and place the private reviewer signing secret in the separately controlled environment. **Do not put real NAR CSV, provider contracts, hashes of sensitive material, secrets or private stage output in the public repository.**

```sh
python -m race_ai.nar_csv_cli \
  --zip /private/20261023_timestamp_race.zip \
  --policy /private/rights-review.json \
  --source-ref https://www.keiba.go.jp/ \
  --rights-ref independently-verified-approval-id \
  --observed-at 2026-10-23T12:00:00+09:00 \
  --event-date 2026-10-23 \
  --venue SOME_ACTUAL_OFFICIALLY_VERIFIED_VENUE \
  --race-number 7 \
  --encoding cp932 \
  --header-mode absent \
  --output /private/unique-nar-preflight.json
```

All filenames/timestamps/venue/rights reference above are **usage placeholders**, not assertions that a valid source file, license, venue or race was retrieved. Match `--encoding` and `--header-mode` to the original CSV after independent inspection; this adapter **does not guess**. No generic `--approved` flag bypass.

The operator-supplied `observed-at` is a claim. The CLI's now clock and the file ZIP timestamp are not an independent proof that the source was captured before bet cutoff.

## Next real E2E gates (no skipping)

1. Source owner review of exact NAR commercial/noncommercial terms for **machine download, private retention, algorithmic analysis/ML training and derived forecast sharing**. Alternatively, a separate approved original structured data source. Until then, **no NAR fetch** and no live prediction.
2. Verify the actual local ZIP format/version/encoding against the documented manual; assign durable horse IDs under a separately legal and auditable mapping. Obtain a separately authenticated official **bet-sales cutoff** and remaining mandatory pre-race feature observations (no odds).
3. Send only validated and rights-approved raw data through the existing `permissioned_source_delivery` + `four_sport_model_suite` using a **new fully populated** current-race snapshot, without injecting missing feature values.
4. Freeze a top8 SHA before official sales cutoff using the independently verifiable `github_freeze_receipt` or a stronger signing/notarization service, with a real remote write receipt and read-back check. No later editing of picks.
5. Verify a formally settled result and revisions separately. Only then compute actual Hit@8. A single E2E success is a milestone, **not full four-sport coverage or 98% proven accuracy**.

Actual real NAR data downloaded in this work: **none**. Independently attested pre-cutoff predictions: **none**. Results externally validated: **none**. New paid services, public deployment and automated betting: **none**.
