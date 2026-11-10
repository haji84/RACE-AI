# BOAT 2026-11-07 registered evaluation and 2026-11-09/10 originals audit

## Decision (evidence-only; not a newly issued forecast)

- The November 7 registered prospective plan is fixed at
  `fe5064e63c2e1c3f5ce32397305f873e89c63cc2`.
  The registration contains the SHA256 of
  `web/product-data.js`, `web/saved-performance.js`,
  and `scripts/boat_budget_plan.cjs`.
- On the subsequent feature HEAD, the latter two Git blobs still match the
  registered commit, but `web/product-data.js` has changed. The newer version
  contains additional official-cutoff-reference parsing and an
  `EXECUTION_FAILED` classification. It must not be substituted for the
  frozen November 7 settlement policy.
- The registered frozen-plan contents, scenarios, allocation, model output,
  and timestamps must **not** be rewritten. Source-free settlement is instead
  executed with exact registered, SHA-matched modules from that pinned commit
  in a private temporary directory. The current result-view implementation
  remains unchanged. If saved evidence is incompatible with the registered
  rule, the settlement must remain `HOLD`, not be recalculated under a newer
  rule. See `scripts/boat_registered_policy.py` and
  `tests/test_boat_registered_policy.py`.

## Evidence searched for 2026-11-09 and 2026-11-10

1. Current authenticated `state/boat-saved-view` V5: the existing
   November 8–10 day-by-day audit reports `HOLD_NO_SAVED_DAY` for November
   9 and 10. This means no dated saved prediction view in that authenticated
   feed, **not** that the venue held no races.
2. `state/boat-private-originals` at inspected HEAD
   `11a3b57570c8e9737c4db9e99d5998246b7359fe`: 39 November
   per-run index records. The newest recorded production session before
   the subsequent source-free display jobs was run `42464724285`,
   dated November 8. The later indexed runs `42805633887`,
   `42808606227`, `42809305971`, and `42810244034` were the
   result/owner-display replay job path, not a verified pre-cutoff
   November 9 or 10 forecast issuance. Its signed source-control latest
   marker still references November 8 and run `42464724285`.
3. The same vault tree has a `state/boat-program-source/v1/2026-11-08.json`
   index, but no corresponding November 9 or 10 date-named program-source
   index. This is an absence in that source index only, not a claim that
   every external data source was unavailable.
4. `state/boat-model-runtime` latest registered commit dates to November 7;
   `state/boat-pdca-encrypted-history` latest commit to November 6.
   `state/boat-all-model-forecasts` is still written by the November 10
   display-only Jobs, but the checked independent readback reported
   `contexts=132, generated_forecasts=0`. Its new cipher alone does not
   prove a new forecast.
5. The GitHub Actions branch-scoped query for the existing nationwide
   forecast workflow across November 9–10 found no ordinary
   `official_national` model-generation job for November 9 or 10.
   The November 10 runs were the explicitly `saved-view:` source-free
   replay, with the forecasting job skipped. Main's result/athlete-statistics
   schedule is a different workflow and does not establish original picks.
6. `state/boat-pdca-transfer` includes private result/statistics archives.
   These were not promoted into original forecasts. Uninspected encrypted
   payloads must not be declared globally absent on a file-name search alone.

## Last independently audited saved-day counts

From GitHub Actions run `42810244034` using authenticated private history:

| Day JST | Saved races | Saved forecasts | Active BOAT model families | State |
|---|---:|---:|---:|---|
| Nov 8 | 132 | 1,526 | 14 | HOLD; 651 applicable model/race slots missing, 130 final, 2 pending results |
| Nov 9 | 0 | 0 | 0 | HOLD_NO_SAVED_DAY |
| Nov 10 | 0 | 0 | 0 | HOLD_NO_SAVED_DAY |

The 132 race rows and 1,526 forecasts on November 8 are not proof of
complete 14×132 issuance. Neither the November 9 nor November 10 results
may be used to create retrospective pre-race forecasts.

## Acceptance gate and references

A November 9/10 original can be restored only if an independently
authenticated physical original is found with the correct event/race,
model/stage/version, original payload SHA, actual persistence time preceding
cutoff, and an independent readback. Else keep `HOLD_NO_PRE_CUTOFF_ORIGINAL`
for formal prediction grading; a newer research reconstruction has to be
labeled separately and never backdated.

- Registered policy: `docs/evidence/2026-11-07/prospective-evaluation-plan.json`.
- Earlier saved-day comparison:
  https://github.com/haji84/RACE-AI/actions/runs/42810244034
- Previously confirmed source-run and physical archive:
  https://github.com/haji84/RACE-AI/actions/runs/42464724285
- Policy bug and code repair: `scripts/boat_registered_policy.py`,
  `scripts/boat_prospective_audit.py`; no keys or plaintext owner URLs.

This audit is bounded to the listed connected GitHub state and checked
execution histories. It does not assert the nonexistence of an unknown private
backup outside those stores or call result-only capture a new pre-cutoff forecast.

## Additional non-GitHub storage checks (2026-11-10 JST)

- Connected Google Drive: a dedicated RACE-AI original-archive folder was
  found. Its two direct files are previous BOAT D+1 audit receipts for the
  November 3 and 4 periods; neither is an authenticated November 9 or 10
  pre-cutoff forecast original. Date/name search across accessible Drive
  returned no corresponding BOAT 9/10 archived original.
- ChatGPT Library + conversation-file semantic search: relevant RACE-AI files
  were historical Excel/CSV analysis or a KEIRIN research report. A distinct
  November 9/10 BOAT frozen original with timestamp/SHA/readback evidence was
  not found.
- Checked November 9/10 main-branch BOAT result/statistics workflow artifacts:
  no standalone original forecast ZIP appeared in the sampled run artifact
  inventories. These are result/statistics executions and cannot stand in
  for immutable pre-outcome model predictions.

Scope qualification: these are accessible folders/search results and selected
GitHub Actions inventories, not an exhaustive assertion about offline personal
backups or all deleted/expired Actions artifacts.

## Native-error cause isolation

After restoring the registered SHA-matched evaluation modules, the frozen
settlement still returned `FROZEN_INPUT_REVIEW_REQUIRED`, an umbrella
error for a *native JavaScript exception*, not a policy-hash mismatch.
To identify the exact checkpoint without exposing user data, the existing
settlement now permits a strictly bounded read-only diagnostic: checkpoint,
exception class, allowed code-module enum, and source line number. No
exception text, stack, race inputs, ticket arrays, credentials, or hashes of
secret material are published. Synthetic native error tests must pass before
running the owner-data audit. The frozen original, model choice, and
registered settlement rule remain unchanged. The actual cause is only
confirmed once a succeeding private runner emits its bounded diagnostic.
