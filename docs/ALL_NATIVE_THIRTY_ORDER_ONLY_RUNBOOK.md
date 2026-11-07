# Thirty native cells: order-only operator runbook

The authorized private research scope is BOAT14/AUTORACE6/KEIRIN5/HORSE5:
eight complete normal races per sport,30 existing models,240 unchanged originals,
and six training/two holdout races per model. Seller remains untrained. Existing
formulas, baseline coefficients, production selection and purchases stay unchanged.

Preparation snapshot,2026-11-07:33 non-BOAT input races were frozen, including
reserves. The retained non-BOAT RESULT supplied one normal HORSE teacher and one
special result; normal eight-case coverage was still pending. This is not a live
status query. A schema-valid draft is neither an execution request nor a fit claim.

## Final manifest and source update

Use `audit/state/all-existing-model-order-only-ci-input.json` with exactly:

| Field | Required value |
| --- | --- |
| `schema` | `RACE_AI_ALL_EXISTING_MODEL_CI_INPUT_V4` |
| `native_artifacts` | Existing BOAT original pins plus authenticated non-BOAT originals/reserves; entries contain only numeric `id` and exact `sha256:` digest |
| `result_artifacts` | Existing results plus newly authenticated generic RESULT pins; same entry shape, preserving revisions |
| `cohort_size` | integer 8 |
| `owner_research_record` | `audit/state/all-existing-model-order-only-fit-request.json` |
| `full_native_boat_cohort` | `true` |
| `keep_other_sports` | `true` |
| `allow_order_only` | `true` |

When a collector RESULT arrives, append its independently verified pin. Add native
pins only for new independently frozen originals. Recheck actual repository,
run/head/name, ciphertext SHA/size, expiry, frozen registrations/cutoff and complete
source replay. Limits are32 unique artifacts,64MiB each and256MiB total.
Do not renew receipts by changing clocks or invent missing labels.

Preserve the older V3 manifest, retained learning pointer and owner MAC. Keep raw
captures, race/entrant identifiers, keys and private paths out of public files/logs.
Do not add draft markers or a common-cohort field to this strict manifest; the
public request fixes30 cells and the wrapper adds `--common-eight-per-sport`.

Offline structure/request checks require no key or network:

```bash
python - <<'PY'
from scripts import all_existing_model_learning_ci as ci
from scripts import all_existing_model_order_only_fit as operator
manifest = ci._manifest('audit/state/all-existing-model-order-only-ci-input.json')
operator._request(manifest)
print('Manifest and explicit request are structurally valid')
PY
```

## Existing Actions execution

Use the existing `Forecast audit viewer contract` job on the approved feature work.
Its operator step requires this manifest and the `official-order-only-fit:`
commit-subject gate. Routine CI does not issue decisions; the video dispatch input
is not a substitute trigger. No new workflow, schedule, cloud service, provider
fetch or local key handoff is needed. Existing Actions secrets provide the key.
After authenticated runtime restoration, the existing step runs:

```bash
python -m scripts.all_existing_model_order_only_fit \
  --input audit/state/all-existing-model-order-only-ci-input.json \
  --restored-dir "$RUNNER_TEMP/boat-production-readback" \
  --out-dir "$RUNNER_TEMP/order-only-fit"
```

The wrapper checks all source archives, then selects complete originals by actual
result-source completion. It retains each cell/race's latest valid native
capture/generation/save. Equal-time conflicts stop execution; winning order and
payout do not select cases. Required cells must agree on roster, cutoff, scope and
result. Only after common eight-case validation does it issue a fresh private owner
V2 MAC and fit. The older MAC is preserved; the new audit is separately encrypted.

## Acceptance and stop conditions

Success requires `ready=true`, `common_eight_per_sport=true`,
`required_common_cells=30`, `record_count=240`, all four `cohort_counts_by_sport`
values equal 8, a bound `common_cohort_sha256`, and verified8/6/2 counts per model.
Original native generation proof is mandatory; derived/journal substitutes are
excluded. Shortage, expired/mismatched evidence, conflicting versions/identities,
inconsistent source closure, or a sixth/seventh availability tie must remain HOLD
before issuance. Pending, special, withdrawals and refunds retain their statuses;
they do not fill missing normal teachers or become ordinary losses.

Upload only `learning.enc`, `learning.json`, `summary.json`; retain the encrypted
owner audit and finish existing independent readback/retention. Local encryption
alone is not an independent save receipt. Preserve held/interrupted state and use
the existing recovery path rather than resetting an uncertain operation.

`rank_confirmed` keeps all 19 original fields, `payout_per_100_yen=null`, false unit
verification and optional observed published money. Its scope is
`ORDER_ONLY_NO_MONETARY_EVALUATION`; monetary PDCA remains HOLD until separate
verified unit/settlement evidence exists. Training, retention, future comparison
and accuracy improvement are separate claims. This run grants no provider licence,
production promotion, purchases or public raw-data release.
