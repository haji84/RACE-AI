# Same-race model evaluation

The new offline experiment contract freezes the complete race list, stages, model/code/artifact versions, chronological windows, feature projection policy and feature eligibility before inference. Every race/model/stage has a row, including `NO_FORECAST` with a reason. Each model in a race/stage binds the same input context and information time. Neither odds nor results belong in the numeric feature projection.

Primary model comparisons use the predeclared feature-eligible common cohort. Runtime failures remain in that cohort. The optional successful-prediction intersection is explicitly descriptive and cannot replace the primary comparison. Reports retain unknown results, excluded official dispositions, missing forecasts, Hit@1, Hit@8 on known results, and the prediction-only rate separately. An unknown result is not a miss and cannot disappear from the denominator.

`EvaluationJournal` stores plans and predictions create-only, checks their hashes before result reading, and reserves result exposure before invoking a label reader. A shared private registry records every possibly exposed race, including training/validation races, so a different experiment name or changed split cannot relabel an exposed race as untouched final evaluation. Interrupted operations do not authorize another source read. The registry is a local ordering control; deleting or changing registries defeats any non-exposure claim and is outside its trust boundary.

Official result observations can arrive later or be corrected. `append_results` adds a separately numbered batch with the previous report hash and the unchanged prediction seal. It requires new result revisions, retains original labels, and never refits or calls a model. Report recovery verifies the complete hash/score chain without reading a source again. If a later batch is incomplete, an explicit `through_batch=0` or another completed batch number recovers that prior report; the interrupted batch remains stopped.

The command line entrypoint is `python -m race_ai.evaluation_cli`. Its register, seal, reveal, append and report operations use local JSON files, explicit expected hashes, and the current local clock. No network or model execution occurs in the evaluation CLI. Input/source truth, cutoff authenticity and permission claims require their own evidence.

## Evidence boundaries

- Retrospective replay of already retained pre-cutoff inputs is research evidence. Already inspected October 15–17 results are development data, not untouched final tests.
- A newly downloaded historical archive has a new capture time. It cannot be backdated to an old information cutoff. Historic day-only result timestamps are not measured physical event clocks.
- Local file hashes and timestamps are not independent pre-cutoff proof. GitHub hash witnesses establish presence of specific bytes at the server time, not provider authenticity, original publication time or final withdrawals/cutoff correctness.
- The complete roster has 19 model IDs. Four B-capable IDs ran on today's retained inputs; unavailable feature semantics or trained artifacts leave the other 15 explicitly blocked. A 19-row matrix is not 19 executed models. No real-data 98% claim is made.
- Existing model families, PR64 assets and the stopped 33-race cohort remain separate and unchanged. No production deployment, paid resource, recurring acquisition or main merge is enabled.

## October 27 observation

One bounded B27 successor observation corrected the earlier observation's missing private input/prediction retention. The original attempt was preserved. At 11:48 JST the new private files retained all 168 discovered races, 3,192 model slots, and 524 forecasts across 131 still-open races. Original LZH/text were not retained. Closed races and unavailable models remain explicit.

The public hash-only commit `50514ea9ba8007f39d02768aee29e53f83e5d77e` contains 131 anchors to a whole private-bundle seal, not individual model receipts. [GitHub witness run 40440865560](https://github.com/haji84/RACE-AI/actions/runs/40440865560) succeeded with server creation time 2026-10-27T02:51:37Z. All 131 anchor blob identities match the prepared bytes. That time precedes 130 planned cutoffs and is late for one. The seal binds the complete bundle and retained facts; private picks and inputs were not published. These counts do not establish final-cutoff/withdrawal authentication or final Hit@8 eligibility.

The separate October 25/26 K acquisitions retained 310 complete races and 1,860 individual rows privately; one incomplete race was quarantined. Their actual capture was 11:59 JST, later than the 11:48 prediction seal. They cannot be inserted into those predictions. Original publication remains unknown. Current-day participants have at most four retained prior observations; no participant reaches the existing five-sample form/consistency requirement. These two archives therefore do not make FULL75 models ready.

The first official-result batch selected three races before acquisition, all with timely GitHub anchors. Three GET attempts returned one scorable normal result, one pending result page and one unavailable/invalid response. The frozen predictions were not regenerated:

| Race | Observation | Four executed models | Other 15 models |
| --- | --- | --- | --- |
| 20261027-23-08 | Normal finish 5-4-3; six registrations matched | Four misses, each 0/1 on known results | NO_FORECAST |
| 20261027-13-04 | Result pending on the observed official page | Unknown, not a miss | NO_FORECAST; result unknown |
| 20261027-22-03 | Source unavailable or invalid; specific cause unproven | Unknown, not a miss | NO_FORECAST; result unknown |

The batch retains all 57 race/model slots. One known result cannot establish relative performance, calibration or a 98% target. This batch has not settled the other 128 locally forecast races. Source operations in this work were B1 + K2 + result3 = six GET attempts; no source retry, paid service or recurring acquisition was enabled.

## Verification and remaining evidence

The generic journal/CLI has offline end-to-end and failure/recovery tests. Today's separately admitted collector supplies real retained predictions and official-result joins; it is not evidence that all 19 engines ran through the new generic CLI. Existing retrospective replay remains development evidence. The train-only implementation is separately reviewed on PR71; its training artifacts are not fitted on the final evaluation labels.

Completing model coverage still requires correctly defined source fields and suitable training artifacts, not just more model slots. Remaining work includes a reviewed connection between the retained real-case format and the generic journal, sufficiently populated historical windows, presentation/weather facts for models that require them, additional official outcomes and untouched future evaluation. New observations must use their actual capture times. No original prediction, held cohort, older failure or final-test designation may be rewritten to fill these gaps.
