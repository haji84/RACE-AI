# RACE AI money contract

Implemented in `race_ai/money.py` and dependency-free `web/money.js`. Browser code exposes `globalThis.RaceMoney`; Node uses `require('./web/money.js')`. Both implementations expose the same snake_case function names and JSON field names. This is a calculation engine for records and estimates. It does not place purchases or establish that a result, probability, or model has been independently verified.

## Numbers and rounding

- Actual monetary inputs and outputs are integer yen within JavaScript's safe integer range, 0 through 9,007,199,254,740,991. Purchases and refunds use 100-yen units. Purchased ticket stakes must be positive; the estimate function accepts zero. JSON numeric values such as `100.0` are accepted only when their value is an integer, then normalized to an integer. Booleans, numeric strings for yen, fractions, missing values, negative amounts, infinities and NaN are rejected with `MoneyError`.
- Probability uses a fraction between 0 and 1, e.g. `"0.10"`. Odds use a multiplier from 1 through 1,000,000. Fixed decimal strings are preferred; finite numeric decimal values are accepted when representable under the same policy. Python also accepts `Decimal`. Inputs allow at most six decimal places and ASCII digits, with no exponential notation in strings. This is the engine's supported estimation precision, not an assertion about a source's odds precision.
- Python uses a local Decimal context with 64 digits. Browser code uses scaled BigInt. Calculated estimates remain canonical decimal strings, including fractional yen. They are not rounded into a fabricated official payout.
- Aggregate return rates are percent strings rounded to six decimal places, half up. Individual expected rates are exact decimal strings. Actual rates are `null` when effective spending is zero. Unknown expectations are `null`.
- Purchase allocation percentages use two decimal places and largest-remainder apportionment, with input order breaking ties. Nonempty purchases display a sum of exactly `100.00`; an empty purchase has an empty percentage array.
- Final payout is `(effective ticket stake / 100) * official payout_per_100_yen`. Official per-100 amounts are positive integer yen. No unofficial odds rounding rule, dead-heat split, or special-payout amount is inferred.

## Public functions

### `estimate_bet(stake_yen, probability, odds)`

Returns `stake_yen`, canonical `probability` and `odds`, and decimal-string fields:

| Field | Meaning |
| --- | --- |
| `payout_if_hit_yen` | Stake × odds; estimate of a hit payout |
| `profit_if_hit_yen` | Hit payout − this ticket's stake |
| `expected_payout_yen` | Probability × odds × stake |
| `expected_profit_yen` | Expected payout − stake |
| `expected_roi_percent` | Probability × odds × 100, or null at zero stake |
| `expected_profit_percent` | (Probability × odds − 1) × 100, or null at zero stake |

For a synthetic 100-yen ticket, probability `"0.10"`, odds `"15.0"`: hit payout `"1500"`, hit profit `"1400"`, expected payout `"150"`, expected profit `"50"`, expected ROI `"150"`. These are arithmetic examples, never live predictions or source observations.

### `validate_purchase(bets, limits)`

A ticket is `{race_id, bet_type, combination, stake_yen}`. `combination` accepts an array such as `[1,2,3]` or a hyphenated string `"1-2-3"`. Boat identities must be distinct integers 1–6. All tickets in one call refer to one race. Optional `probability` and `odds` must be supplied together; a manual ticket may omit both.

| `bet_type` | Boat count | Identity order |
| --- | --- | --- |
| `trifecta` | 3 | Ordered |
| `trio` | 3 | Sorted, unordered |
| `exacta` | 2 | Ordered |
| `quinella` | 2 | Sorted, unordered |
| `quinella_place` | 2 | Sorted, unordered |
| `win` | 1 | Single boat |
| `place` | 1 | Single boat |

Duplicate tickets are rejected after normalization, including reversed unordered combinations. Identifiers use 1–128 ASCII letters, digits, underscores, periods, colons or hyphens. A purchase accepts at most `max_bets`, default 8, configurable to 16, 24 or 32.

Supplied probabilities for distinct standard mutually exclusive tickets of the same type (`trifecta`, `trio`, `exacta`, `quinella`, `win`) cannot sum above one. The guard does not sum overlapping `place` or `quinella_place` events. This engine's forecast contract assumes standard strict-order outcomes; tie-specific forecasts require a separately defined probability model. Official dead-heat settlement remains supported from the explicit winning payout rows.

`limits` requires `budget_yen`. Optional fields are `day_budget_yen` (default race budget), `day_spent_yen` (default 0), `loss_limit_yen` (default race budget), `loss_used_yen` (default 0), and `max_bets`. All counters are nonnegative integer yen. Race/day budgets and daily gross-spending counters use 100-yen units; a loss limit/counter may contain any integer yen after a special payout. Proposed spending must fit all remaining limits. Invalid or missing configuration is rejected.

Returns normalized `bets`, `total_stake_yen`, `budget_yen`, `remaining_budget_yen`, `allocation_percent`, and aggregate `expected_payout_yen`, `expected_profit_yen`, `expected_roi_percent`. If any ticket lacks probability/odds, all aggregate expectations are null. Expectations sum linearly; this function does not infer a portfolio loss distribution or assume tickets are mutually exclusive.

### `settle_bets(bets, official_result)`

The caller supplies a complete result whose source and completeness it has verified. Required result fields:

```json
{
  "race_id": "20261015-18-01",
  "status": "settled",
  "confirmed": true,
  "payouts": [
    {"bet_type": "trifecta", "combination": [1, 2, 3], "payout_per_100_yen": 1500}
  ]
}
```

The example is synthetic. `confirmed: true` is a caller assertion, not cryptographic source evidence. An unconfirmed, pending, mismatched or missing result is rejected instead of recorded as a loss. An explicitly complete, empty payout list means every effective purchased ticket missed. Prediction-time odds cannot affect final settlement.

- `settled`: apply every listed winning combination; other effective tickets miss.
- `dead_heat`: apply every listed winning combination independently; use each official value without dividing or inventing it.
- `special`: require nonempty `special_payouts`, e.g. `[{"bet_type":"trifecta","payout_per_100_yen":70}]`. The number 70 is an explicit synthetic input, never a default. Apply it to effective tickets of that type. Ordinary payouts may coexist for other types. Duplicate or conflicting ordinary/special entries are rejected.
- `cancelled`, `no_contest`, `postponed`: return the whole purchased amount and set effective spending to zero. These statuses represent an official confirmed refund disposition; a mere schedule change is not sufficient. Contradictory winning payouts are rejected.
- Optional `refunds` contains `{bet_type, combination, refund_yen?}`. Omitted `refund_yen` means the full stake for that held ticket. Explicit refund yen supports a subset of its 100-yen units, is positive and cannot exceed the held stake. Effective units alone receive a winning or special payout. The result adapter must enumerate official refund combinations; the engine does not infer refund rules from a flying start, absence or disqualification label.

Returns `race_id`, `status`, `total_stake_yen`, `refund_yen`, `effective_stake_yen`, `payout_yen`, `cash_return_yen`, `net_profit_yen`, `actual_roi_percent`, and per-ticket `rows`.

`cash_return_yen = payout_yen + refund_yen`; `net_profit_yen = payout_yen - effective_stake_yen`; ROI uses payout / effective stake, excluding refunds from numerator and denominator. For four 100-yen tickets and one official 1,500-yen payout, profit is 1,100 yen and ROI is 375%. A full refund produces zero profit and null ROI. A partial refund preserves the separate cash movement and decreases effective spending.

### `recommend_allocation(candidates, limits, model)`

Candidates use the ticket shape above, with probability and odds when available. The helper validates input and rejects duplicate candidates. It considers at most 120 candidates per race.

The helper returns `status: "skip"` unless `model.validated === true` and `model.data_complete === true`. Eligible candidates must have strictly positive expected profit (`probability * odds > 1`). Rank them by expected return with stable input-order ties. Assign only one 100-yen unit per selected ticket, within the configured count cap, remaining race/day/loss limits, and an additional 10% of the race budget. Unused budget remains unused; a budget below 1,000 yen cannot fund a 100-yen recommendation under this conservative cap.

Returns the purchase summary plus `status` and `reason`. Reasons are `model_unvalidated_or_data_incomplete`, `insufficient_expected_value_or_risk_budget`, or `validated_positive_ev_one_unit`. The caller must establish model validation, as-of availability, calibration and suitability; the boolean fields do not themselves establish those facts. This helper makes no optimized-risk or guaranteed-profit claim.

### `append_purchase(ledger, record, limits)`

Returns a new normalized ledger array after all validation succeeds. It does not mutate inputs, save localStorage, execute a purchase, or transmit data. The caller may persist the returned array atomically after success.

A record is `{id,race_id,purchased_at,bets}`. `purchased_at` requires an ISO timestamp with timezone and seconds; fractional seconds may have 1–3 digits. Calendar rollovers, naive timestamps and invalid offsets are rejected. The engine derives `purchase_day` in Asia/Tokyo and sets `source: "manual"`. Optional `official_result` is validated through the same settlement engine. Purchase ids and race/ticket identities cannot repeat anywhere in the ledger.

The helper enforces the cumulative race budget and point cap across previous records, total same-JST-day gross spending, and same-day loss exposure. Loss exposure conservatively sums pending stakes and each confirmed record's nonnegative loss; wins do not increase the allowance. Explicit `day_spent_yen` and `loss_used_yen` cover additional activity outside this local ledger, so callers must not repeat ledger totals in those counters. At most 10,000 records are accepted.

The helper does not reconcile official result corrections or manufacture missing provenance. The history layer must retain immutable result revisions and rerun settlement from the selected complete official revision.

### `summarize_ledger(ledger)`

Validates all records and returns `purchase_count`, `settled_count`, `pending_count`, `total_stake_yen`, `pending_stake_yen`, `settled_effective_stake_yen`, `payout_yen`, `refund_yen`, `cash_return_yen`, `net_profit_yen`, `actual_roi_percent`. Counts refer to purchase records. Pending records are reported separately and do not become realized losses or enter the actual-ROI denominator. Empty or fully refunded confirmed spending has null ROI.

## Verification

`tests/test_money.py` tests calculations, validation, risk limits and immutable manual records. `tests/test_money_parity.py` executes the actual shipped Node module and Python implementation with the same literal cases, compares their complete outputs, and independently asserts specified expected values or rejections. Cases include the handover arithmetic, changed odds, misses, full/partial refunds, multiple dead-heat winners, explicit special payout, cancellation, empty spending, malformed/nonfinite/negative inputs, duplicates, budget caps, JST dates, pending results and safe-integer/decimal boundaries.

Run `python -X utf8 -m unittest discover -s tests -p 'test_money*.py'`, then the complete `python -X utf8 -m unittest discover -s tests`. Node is required for parity verification. `docs/evidence/money-contract-2026-10-15.json` records synthetic expected and actual outputs; it is calculation evidence, not evidence of live odds, prediction performance, official source access, or real purchases.
