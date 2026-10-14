# Official single-race update observations

`official_race_updates.py` reads supplied official beforeinfo, odds3t and
raceresult HTML. It validates the dated twelve-race schedule, selected race,
venue and closing time before extracting factual fields. The current site
uses header color3 for upcoming races and color2 for finished races; both
non-selected styles are covered by tests.

Preview data includes six registration/lane identities, display times,
exhibition ST and available weather. Current-race actual ST/finish never enter
this schema. Result data separately contains finish dispositions, actual ST,
explicit per-100-yen payouts and returned boat numbers. Start display order is
retained as evidence; actual/preview course remains null until independent
course proof is implemented. Image filename metadata is used only to identify
boat numbers; no images or video are fetched or stored.

Odds enumerate all120 distinct trifecta combinations. Missing values remain
null. The official 締切時オッズ label marks a final market that can never be
used as pre-race evidence. Generic data-not-ready pages become PENDING with no
facts and body_identity_verified:false. A dated result-not-published message
remains PENDING. HTTP/source failures are separate states.

## Financial readiness

Finish confirmation and financial confirmation are separate. Available and
verified market types are recorded explicitly. Normal exact winning-combination
coverage is required, including both place winners and all three quinella-place
pairs. A market's mere presence cannot certify unlisted winning combinations.
All dead-heat markets remain gated pending full tied-winner coverage. Explicit
special payouts use only observed official amounts. Returned boats are retained
as facts, but bet-specific financial refund mapping is gated rather than guessed.

A partial payout table has global confirmed:false and settlement_ready:false.
`settlement_for_market` exports only a positively verified market and includes
verified_market_types so the shared money engine rejects another purchased type.
Explicit race cancellation/no-contest supports full-race refund. Postponement
alone remains pending; it requires explicit full-refund evidence before becoming
confirmed. No result is inferred from closing odds or the winning triple alone.

Known program registrations can be reconciled using the existing generic result
reconciler. The existing Tokuyama individual-result bridge is reused through an
in-memory projection of verified cells when its supported dispositions apply.
The source URL/hash continues to refer to the actual fetched original.

## Append-only history and time boundaries

`official_observation_store.py` creates official_observations plus UPDATE/DELETE
rejection triggers. Identical retries reuse the same content-addressed snapshot;
changed observations append numbered revisions. Source publication time is
unknown, so available_at must equal captured_at. Actual saved_at comes from the
server clock and cannot be supplied by the caller.

`latest_observation(...,as_of=...,pre_race_only=True)` requires availability,
capture and actual save before the as-of cutoff. It additionally excludes final
odds/results and observations first saved after closing. A backdated import
cannot become actual pre-race performance evidence. Parser eligibility and
storage_eligible_pre_race are separate fields; the pre-race query enforces the
stricter storage gate. Database triggers protect the normal application path,
not an administrator able to alter schema/files or the process clock.

## Single-race operator command

```powershell
.venv/Scripts/python.exe -X utf8 -m race_ai.official_update_worker --date 2026-10-15 --venue 02 --race 1 --kind beforeinfo --review config/operator-official-facts.json --db <protected-db-path> --execute
```

Omitting --execute performs no network requests or database creation. Each
execution retrieves one chosen endpoint for one chosen race with a 1MB cap,
10-second timeout and no redirects. The review must cover that exact endpoint
scope and factual ingestion/storage. Sibling-source permission is insufficient.
The CLI writes normalized observations, never source originals.

## Evidence and limitations

Actual bounded historical Tokuyama20261014/1R observations on20261015 produced
six preview records,120 closing odds and six finish/actual-ST records. The normal
actual result table contained all seven verified monetary markets. All three
captures and actual saves occurred after that race; all pre-race queries return
null. These observations are structural/history evidence, not pre-race
prediction performance. Source URLs, hashes, capture/save times and snapshot IDs
are in evidence/2026-10-15-official-race-updates.json.

A separate actual current-day Toda20261015/1R crosscheck matched the official B
program against the official race-list body for all six lane/registration/motor/
boat tuples, closing time and whitespace-normalized names. Evidence is in
2026-10-15-B-racelist-crosscheck.json. This is one verified race, not nationwide
individual-page reconciliation.

The parser/store/worker and independent payout-coverage tests pass. Cancellation,
postponement, special payout and tie cases are synthetic rejection contracts;
these exceptional real source cases were not observed. This lane does not add
bulk polling, cloud persistence, automatic betting or measured model accuracy.
