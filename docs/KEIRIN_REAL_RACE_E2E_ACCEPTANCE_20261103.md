# KEIRIN real-race end-to-end acceptance gate | 2026-11-03 JST

## Decision
**Real-race end-to-end NOT PASSED. Fully automated collection, training, forecasting and production release remain disabled.**

This report distinguishes (A) a real candidate result page fetched in a one-shot private research test from (B) a synthetic model/save integration test. Do not combine their successes into a false "real E2E" completion claim. Prior predictions stay immutable.

## A. Real results transport and reference comparison
1. KEIRIN.JP official historical page: [run #41557206587](https://github.com/haji84/RACE-AI/actions/runs/41557206587): synthetic parser 12/12 passed; actual HTTP response **500**, real official result unverified.
2. Alternative third-party `keirin-mobile.jp` historical result (2026-10-22 Odawara 2R): [run #41558392063](https://github.com/haji84/RACE-AI/actions/runs/41558392063): page obtained, unambiguous 3連単 candidate `1-6-7`, payout `2,670円/100円`; 12/12 synthetic tests passed. This is NOT KEIRIN.JP or a licensed bulk stream.
3. Actual 2026-11-03 Odawara 1R: [run #41558697314](https://github.com/haji84/RACE-AI/actions/runs/41558697314): one page `https://www.keirin-mobile.jp/top/result.php?date=20261103&jcode=36&race=01`, source SHA-256 `58010ea810d7ac3bdfd1842fc3860581891e1bee04803509a3383efff3ab3f81`, candidate `6-1-5`, `11,480円/100円`, runner captured 2026-11-03T01:17:00+00:00, no raw HTML stored. **Unverified third-party candidate, not official final result proof.**
4. Earlier user chat's morning research baseline `20261103-am-reference-v1` created at `2026-11-03T08:10:15+09:00` listed eight picks for Odawara 1R `202611033601`: `5-1-4, 5-1-7, 1-5-7, 1-5-4, 1-4-7, 4-1-5, 4-1-7, 1-4-5`. This doesn't include `6-1-5`, so **research_hit8=false conditionally on that candidate**. Baseline `officially_frozen=false`; cannot be promoted to formal Hit@8, and not backfilled as a verified external pre-cutoff freeze. No claim of measured model improvement.

## B. Modules added to existing Draft PR #72, not main
- `race_ai/keirin_mobile_one_shot.py`: bounded no-redirect one-page transport for published alternative source, parser extracts only an unverified result/payout candidate; no recurring collector or raw HTML retention.
- `race_ai/keirin_candidate_audit.py`: fail-closed research comparison against earlier unchanged top8. Validates race/date/source/hash/cutoff alignment.
- Already existing `race_ai/keirin_result_delivery.py` / `race_ai/evaluation_result_revision_bridge.py` provide **separately admitted** normalized result schema and append-only revision contracts.
- `race_ai/keirin_result_reactor.py`: an independently authenticated FINAL_NORMAL/no-refund result can enqueue a verified future race outbox intent, bounded by actual cutoff. No model execution or result fetching inside.
- `race_ai/keirin_next_forecast_worker.py`: private-owner callback-based consumer for an outbox intent. Rechecks scope, rights, source SHA, pre-race timestamp, cutoff margin, current freeze state; executes delegated model; validates exactly 8 distinct valid tickets; attempts create-once private store with exact readback and independently checked pre-cutoff receipt. It does **not** supply any actual provider grant, private service, model weights, legitimate remote timestamp attestor or 24-hour daemon.
- All in existing PR #72 branch `feat/p0-offline-discovery-gate-20261022`. PR #71 remains separate; no new PR, main merge or permission changes.

## C. Synthetic end-to-end evidence, strictly not real
[GitHub Actions run #41560026472](https://github.com/haji84/RACE-AI/actions/runs/41560026472) on commit `d294da73c5759bf7b6f7c81c9bf4e5592804dafd`, completed/success:
- owner-worker 14/14 synthetic
- result-reactor 15/15 synthetic
- source candidate auditor 11/11 synthetic
- joined result event -> research comparison -> outbox -> fake model -> mock private freeze/readback 2/2 synthetic
- 42/42 total; no external source GET in this run, mock external witness cannot certify real timestamp.
Thus the **software contract path is connected and tested**. The real-source, real-model, true private freeze and pre-cutoff evidence path is not.

## D. Blocking acceptance requirements
1. Obtain source-specific permission or authorized contract for automated result intake, storage, analysis/learning, rate, and pricing. Browsable data does not imply unlimited automated use. Publisher rights evidence must be independently verifiable.
2. In a trusted private runtime, receive **one real officially confirmed** result and payout (or authenticated licensed provider feed); ensure cancellations, refunds, revisions, tie handling, and original source hash.
3. Read an untouched, independently externally timestamped pre-cutoff prediction original for the *same* earlier race; compare and save an append-only audit. Reconcile all race IDs with official day cohort.
4. For a **new future** race with source snapshot and authorized purpose, run the actual PR #71 model using only pre-cutoff observations, not the already completed previous race outcome as a pre-race feature; create-only save exactly 8 picks and independently verify remote persistence **before official cutoff**. Read it back and reconcile model version/input digest.
5. Trigger the authorized result event to dispatch an idempotent outbox job on a real host, prove a single real-race cycle and recovery without changing previously frozen predictions.
6. Recheck one future race after it ends; audit actual results and A/B candidate models without results leakage. Only after evidence 1-5 can production monitoring be considered through a separate explicit owner approval.

## Guardrails kept
No scraping across entire race catalog; no public raw third-party data; no betting/payment; no model auto-promotion; no merging `main`; no persistent live poller. Formal Hit@8 remains **unverified**, not 0%. Do not use this fixture-only test as real E2E completion.

Source policy: https://keirin.jp/pc/dfw/portal/guest/policy/index.html


## E. 2026-11-03 10:44 JST: pinned real PR71 algorithm in one synthetic full cycle

- Existing Draft PR #72 now contains \`race_ai/keirin_pr71_model_adapter.py\`, \`race_ai/keirin_owner_one_cycle.py\`, \`tests/test_keirin_pr71_model_adapter.py\`, \`tests/test_keirin_owner_one_cycle.py\` and dedicated pinned-checkout CI. No new PR, no main merge, no unsanctioned provider network traffic.
- **CI evidence**: https://github.com/haji84/RACE-AI/actions/runs/41561632885, HEAD \`4ac7faf19bdd03108f6a2ee4160674ae584250bf\`, completed/success. 5 actual-PR71-adapter tests + 15 result-reactor tests + 14 owner-worker tests + 2 full synthetic cycle tests = **36/36 passed**. All inputs/results and rights callbacks here are synthetic; two runs of the actual PR71 algorithm were invoked by tests. PR71 source is pinned to \`1ee8579a9cb758ddcf0fa4a6ceb6912fc317ac76\`.
- Full synthetic cycle: fictional KEIRIN final result -> supplied-result adapter -> immutable revision record -> research-only Hit@8 -> guarded next-race outbox -> actual PR71 scenario-model computation on fictitious evidenced fields -> 8 valid 3連単 -> mock owner-private write/readback -> mock timestamp-receipt interface. Results and earlier picks are unchanged. The synthetic grant-denied case stops before model calls. No live dataset access.
- **Corrected model provenance**: PR71's untrained weights must not be given a fabricated \`trained_until\` timestamp. The private worker can accept \`trained=False, trained_until=null\` only for \`...-UNTRAINED\` models. It still rejects missing evidence, a changed snapshot SHA, expired/cutoff-late input, market/results leakage, invalid tickets and uncertain writes.
- **Real E2E still blocked**: There is no verified provider-authorized result feed for automated retention/learning, no fully witnessed real PR71 pre-race feature snapshot (8 common + 4 KEIRIN required per rider, mandatory weather/bank evidence and timestamps), no actual owner-private atomic store/independent external receipt, and no verified one-future-race creation before cutoff.
- The real one-shot 2026-11-03 Odawara 1R candidate \`6-1-5\` and reported \`11,480円\` were observed on a third-party web page, not admitted as an authenticated official result or backdated to a real freeze. They cannot be used to label the next model's past before its source publication/capture time.
- **Production guard**: auto-polling, unattended learning, auto-promotion, paid provider onboarding, third-party raw-data redistribution, main merge, and wagering all remain disabled. Formal Hit@8 = null, and synthetic CI is not a live production pass.
