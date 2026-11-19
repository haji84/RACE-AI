# 2026 historical published lineups: measured progress (2026-11-19 JST)

## Confirmed scope
- Result/payout universe: 24,291 settled races, 2026-01-01 to 2026-11-18.
- Applicable men's races: **22,245**. Girls races: **2,046**, not classified as men's lines.
- Previously source-linked: **6**. Added another **9**, all with matching actual starters and published race orders.
- **15 source-linked historical published lineups; remaining 22,230; invalid/conflict 0.**
- Classified within those 15: SAME_LINE_3=2, SAME_LINE_2_PLUS_OTHER=10, THREE_DIFFERENT_LINES=3.
- These proportions apply to the **15-item pilot only**, NOT the national sample. No training/adoption changes.

## Retained data
- `published_lineup_pilot_20261118.jsonl`: original six source-linked entries.
- `published_lineup_more_verified_20261118.jsonl`: another nine entries from Kokura, Ogaki and Utsunomiya, sourced to the archived public page URLs.
- `line_matched_15_verified_20261118.csv`: per-race result, source, lineup, line classification, pair finish places and singleton positions.
- `line_coverage_15_pilot_20261119.json`: counts and status.

## Backfill pipeline
- `historical_line_backfill.py`: bounded newest-first daily venue page collector, explicit robots.txt check, 2s request spacing, stop-on-denial, starter-set matching, source URL/hash, and nationwide coverage recomputation.
- `.github/workflows/keirin-line-backfill-research.yml`: research-branch push/manual trial; default 12 pages/run and maximum 100, no main changes and no Secrets.
- **Collector implementation is committed, but a successful real GitHub Actions harvest is not yet evidenced.** Do not raise the matched count until new real saved rows are independently read back.
- Provider 403/429/robots denial is HOLD. No rotating UA, proxy or bypass.
- Historical line forecasts are NOT observations of the final on-track grouping. The old source ZIP has results but no line originals; car numbers alone must never be used to invent line affiliations.

## Historical source examples
- https://kantoumon.jp/20261118_kokura
- https://kantoumon.jp/20261118_ogaki
- https://kantoumon.jp/20261118_utsunomiya

## Next needed to close
Recover and match actual published lineups for the remaining 22,230 men's races. When one archive/source does not cover old dates, record 404 or missing and use another legitimate public historical source. Preserve the denominator and source coverage by month/field size. Do not mark an unexecuted workflow as a completed fetch.
