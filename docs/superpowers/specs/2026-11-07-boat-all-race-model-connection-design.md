# BOAT all-race model connection

Owner request: require exhibition for the actual race entrants, parse every venue's racecards, execute post-exhibition forecasts across the race ledger, connect existing model families to real histories/features/fitted models, unify site intake, and show racer names. Repeated owner instructions to proceed supply execution authorization; no repeated design approval gate.

## Approach

Extend the existing GitHub-only collector, existing native models and encrypted display feed. Preserve original forecasts, their cutoffs and all result revisions. Reuse the concurrently integrated venue research and historical source paths. No provider, repository permission, charge, main merge or active-worker control is added.

Racecard parsing owns the source roster. Explicit withdrawals remove entrants from the exhibition requirement; an absent exhibition value alone never declares withdrawal. Physical lane numbers remain 1..6 and may be non-contiguous. Predictions contain only official active entrants. Trifecta requires at least three active entrants and up to min(8, permutations(N,3)) saved combinations. Cancelled/no-contest/unpublished races retain explicit states.

Use an owned adapter over the pinned parser, preserving URL/day/venue/race/roster/cutoff checks while supporting navigation/statistics layout variants. Missing actual statistics stay missing. No historical page read is presented as a new pre-cutoff forecast.

Build real native inputs from official program/beforeinfo contexts and verified historical records before the prediction as-of. Reuse existing learned artifacts; fit genuinely missing learned families with distinct historical outcomes and chronological separation. Never relabel fixed weights as learned. Where required observations are unavailable, a versioned, explicitly sparse input path may omit their terms with missingness metadata; the fully observed old model path and saved originals remain unchanged. No invented humidity/tide/start/history values. Insufficient training remains visible rather than fabricated.

All applicable families/stages get an execution or explicit readiness record; specialist sports and daily-selection strategies retain their applicability rules. A missing model must not suppress ready models. Publish projections of actual saved native outputs and existing history pairs together, retaining immutable original identities and provenance. Encrypted feed evolution allows append-only forecast additions and name enrichment, rejects original removal/replacement, and keeps the owner URL/root-key separation.

Names bind by official registration identity, preferring same-race program names and then a verified racer registry. Name enrichment is display metadata and never changes predictor features or hashes. Unknown names remain unknown.

## Validation

Synthetic 3/4/5/6-entrant cases, non-contiguous lanes, withdrawal vs unpublished, all venue identities including legacy navigation variants, wrong identities and payout/roster mismatches. Complete six-entrant existing predictions must be unchanged. Real retained source replay and source hash checks validate adapters without retroactive forecast claims. Test model-by-model dispatch with genuine training fixtures, future-data rejection, append-only encrypted feed union, name identity binding, browser budgets/model choice preservation and results/returns. Verify the existing URL and report live pre-cutoff collection separately from offline replay; no claim of universal future source availability or improved hit rate.
## Source-original privacy completion

Before enabling the updated source worker, its existing first/supplement P0,
five-model P1, result journal/CSV and complete continuity artifacts must also
use the configured owner key. New outer GitHub artifacts contain only
`private-original.enc`; the encrypted inner ZIP preserves every original byte.
The source-only verification bundle contains code and remains separate.

Readers verify the actual outer GitHub ZIP digest and repository/run/head/name
before decryption. Native JSON member hashes and GitHub `created_at` stay
unchanged. Old clear artifacts remain readable without rewriting them or
fabricating new receipts. Encryption failure stops the corresponding upload.
The root key stays in Actions; no provider, key replacement or permission
change is introduced.

An existing host supervisor reads a separate count-only control artifact,
bound to the actual encrypted continuity bytes and both GitHub receipts. Its
schema permits only operational counters, day, fixed stop/wait enums and run
identity. The owner key remains in Actions. Missing or inconsistent companion
control holds encrypted predecessors; the legacy clear-checkpoint reader remains
available without granting the host decryption access.

Before a new bounded session starts, an early source worker may wait without
source requests for T-15 from its authenticated restored P0 schedule. It retains
the original 330-minute physical handoff and 30-second maximum sleep/heartbeat.
The source limits remain 240 requests/session, 45/round, 24 rounds, 65 minutes
and 180-second polling. No-future-window completion preserves sealed counters
and source denials and records a day handoff; the host waits until next JST
midnight after enforcing incomplete-transaction, denial and hard-stop guards.
