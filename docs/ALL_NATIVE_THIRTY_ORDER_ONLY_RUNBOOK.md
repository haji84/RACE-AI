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

## Explicit order-only future comparison

`race_ai.all_existing_model_order_only_pdca.score_order_only_pairs_artifacts`
provides a separate path for authenticated AUTO/KEIRIN `rank_confirmed` labels.
The existing cash PDCA API continues to reject them. HORSE cash labels and BOAT
results are outside this new typed path; this API does not convert them or establish
completion of all30 cells.

Pass the unchanged future-pairs ZIP, its freshly fetched actual artifact metadata,
the official RESULT ZIP and its own fresh metadata. Bind the expected run/head
separately for each source. All RESULT rows must replay against independently
authenticated frozen native inputs before filtering. If a day RESULT contains
other races, supply their original native archives through
`additional_native_artifacts`, each with `raw`, `metadata`, `expected_run_id` and
`expected_head_sha`. Those extra inputs never become forecasts or losses. The
function fits no model, issues no forecast and makes no provider request.

The private record preserves the original19-field label, its full SHA, original
source closure/receipt, exact roster/cutoff and both original native forecasts.
Probability outputs supply winning-order probability, full native rank and log
loss with the documented floor `1e-15`. Selection outputs supply native ticket
coverage/hit and abstention; three/five plans remain separate where present.
Comparison uses the same result within each cell's paired cohort. Missing,
pending, special or cash-only teachers remain unscored; abstention is not a miss.
No stake, return, ROI, recovery, profit or payout metric is calculated or displayed.
The original optional published amount remains private evidence with unknown unit.

The output directory contains only opaque partitions, each holding
`learning.enc`, `learning.json` and `summary.json`. The aggregate counts sidecar
is written beside that directory and must not be added inside its ZIP. Preserve
existing approved encrypted retention; no new workflow or schedule is required.
After upload, fetch the actual ZIP/metadata and call
`verify_order_only_pdca_artifact(raw, metadata, now=..., expected_run_id=...,
expected_head_sha=...)`. Its name must match
`all-existing-model-order-only-pdca-<run>-<round>`. Independent readback verifies
every source forecast is present, rejects partial/mixed contexts, and replays at
the stored original evaluation time. Local readback alone is not this receipt.

Inherited limits remain64MiB per archive and12MiB per encrypted partition, with
256MiB total source inputs. Shortage, source mismatch, cutoff/roster conflict,
expiry or an over-limit archive must stop without relaxing those limits. Synthetic
tests and independent code review cover this path. Actual future30 scoring and
realistic full30 archive-size acceptance still require future authenticated data.

## Actions entry for typed nonfinancial PDCA

Use the existing production acceptance job with commit subject `order-only-pdca:`
and the public manifest `audit/state/all-existing-model-order-only-pdca-input.json`.
It must have exactly `schema: RACE_AI_ORDER_ONLY_PDCA_INPUT_V1`,
`future_artifact`, `result_artifact`, and `additional_native_artifacts`.
Each pin has only `id`, `digest`, `run_id`, `head_sha`; extras are unique and at
most16. The script runs in trusted same-repository PR71 Actions with the existing
owner secret, never a local-key handoff:

```bash
python -m scripts.all_existing_model_order_only_pdca \
  --input audit/state/all-existing-model-order-only-pdca-input.json \
  --out-dir "$RUNNER_TEMP/order-only-pdca"
```

The workflow uploads only the opaque partition directory when typed pairs exist,
then invokes `--readback-artifact <actual-id>`. Status is stored separately and
projects counts and hashes. Existing per-partition public summaries contain
aggregate model statistics without raw labels, inputs, coefficients or ticket
lists. Old output and generation files are never reset after a held readback.
This entry neither trains nor issues forecasts and makes zero provider requests.

## Thirty-cell future input and original provenance

After a real thirty-cell candidate is independently saved, the existing
`native-p1-compare:` Actions entry accepts native-future manifest V3. Exact fields:
`schema: RACE_AI_ALL_NATIVE_FUTURE_INPUT_V3`, `candidate_cell_count: 30`,
`candidate_artifact_id`, `candidate_digest`, and `source_input_artifacts` (one to16
unique four-field pins as above). Keep V1/V2 dictionaries and old proof intact.

The candidate must pass common-eight/240-record/owner-V2 checks. Each produced
sport must have all its original native cell inputs for one race, with the same
registered roster/cutoff/scope and a genuine baseline. Missing learned baselines,
old native model clocks, incomplete cases and already-issued candidate/race
predictions remain reasoned HOLDs. A sport may be absent without claiming all30
were produced. New capture after fitting can resolve a real clock shortage;
rewriting an old snapshot clock cannot. All forecasts need the existing ten-minute
margin and an actual candidate receipt before their decision time.

V3 also seals exact original source admissions/clocks, generation MAC, manifest
and every opaque member SHA into private `<out>.origin/origin.enc`. Only this
cipher is uploaded separately as `all-native-future-origin-<run>-900010`. The
original source/generation JSON files remain private. The existing workflow passes
both `--readback-artifact <pairs-id>` and
`--readback-origin-artifact <origin-id>`. Complete independent receipt proof is
true only after both fresh metadata/ZIP/cipher/bundle/member checks pass. The
physical origin-generation time must precede its actual save (including the
one-second server precision rule) and keep the cutoff margin. Pair-only
compatibility does not claim an independent origin receipt. Preserve the cipher,
actual metadata and original source archives under the existing retention policy.

The fixed input/archive/crypto caps remain; oversized real data must HOLD.
Twenty-two synthetic V3/legacy tests and independent review passed. Real thirty-cell
fit, full real thirty-cell future execution and realistic archive-size acceptance
remain separate, incomplete gates.
