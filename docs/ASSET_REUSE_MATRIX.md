# Asset reuse audit — 2026-10-21 JST

## Current read-only refresh — 2026-10-25

Main remains `8bb7d69f9c8fb302055bc9e2609903d1e8f73e4b`; Draft assets below are not integrated. Earlier rows are historical evidence.

|PR|Current head|API base SHA|Current exact-head CI|
|---|---|---|---|
|61|fef68607b4773c59d6d46aa04b9e9762a42683d4|8bb7d69f9c8fb302055bc9e2609903d1e8f73e4b|No runs returned|
|64|761247bee0209e37b1af6b8885e92cad3e9260a5|8bb7d69f9c8fb302055bc9e2609903d1e8f73e4b|40049863446 success|
|65|989ffff1d6d2a3476dab41655038eda43f94fff7|2ca60a885a5d61dabcf267175c7a6d3bf05faad5|39951519264 /39951519516 success|
|69|bca59ebc5c7174e79d2dba027a97890f5d0d3d1f|8bb7d69f9c8fb302055bc9e2609903d1e8f73e4b|39696481097 success|
|71|a3d4d011fab8773e2eab07ca83580ab345dfb708|070907dd335f1e0d64d31b49c2bb799e54010be3|40059352693 success|
|72|96afca652d6edaac493bb9845ad361122e58fb33|bca59ebc5c7174e79d2dba027a97890f5d0d3d1f|40117996609 success|

PR64 full514 changed paths were enumerated locally. Reuse its K/B/parser/history source assets read-only. PR72 publication/binding/receipt/settlement and PR71 original model/validator/odds audit/UI assets provide the current bridge; coefficients and original prediction bytes stay unchanged. PR65 remains a pilot. PR71/72 share merge-base070907dd, not current PR69; no automatic stack integration is inferred. Source-rights and product exit tiers are in `SRC_RIGHTS_STATUS.md` and `REQUIRED_EXIT_GATES.md`; current AllowedPaths/writer ownership are in the parallel taskboard.

Integrated base: main `8bb7d69f9c8fb302055bc9e2609903d1e8f73e4b` (README only).
New unit starts directly from this base, not the stacked PR64 tree. Original PR64 checkout and uncommitted Cloudflare work remain intact.

| PR | Exact fetched head | Dependency / observed PR CI | Disposition |
|---|---|---|---|
|59|`5a38336727c452ef0ba796f56b68434fe7b59837`|base private-Blob stack; 38837817146 success|Keep trusted OIDC writer untouched; real storage integration needs separately verified access/pins.|
|60|`efd12cac792cc7100387a1f4952db128d422e125`|59; 38608857764 success|Purpose rights/date-bound collector pattern; not a four-sport grant.|
|61|`fef68607b4773c59d6d46aa04b9e9762a42683d4`|main; no runs returned by PR-run lookup|Read AGENTS, STATE, ROADMAP, 53 chapters, 98% amendment, Actions delta and integrated priority. Specification reference, not implementation/approval.|
|62|`a6bc73d97d56e0f6626450e1883000763feb0643`|59; 38611271330 success|Preserve 7-view UI/manual16/24/32; defer integration until data/security.|
|63|`eee30c0af9ec0c2532eaab82943d7dc251d2d77f`|59; 38612150125 success|Reuse strict reader behavior later; no new token or fallback HTTP.|
|64|`27f3df12ddca3971833d4dbf03f6fbcc88df6b07`|main plus historical stack; 39001100239 success|Extract only pure ranking functions below. Do not change head, held POST or assets.|
|65|`dd832f5910423b2be2d9d25d0f04c9f08d4dc417`|PR64 base snapshot; 38831059323 success|Read-only controller concepts; never merge authority.|

These read-only CI queries returned PR-associated runs, not every push run. Historical success is not new-unit CI or main integration.

KEIRIN-AI: main `c922c56079d087ee34e6ec4533bf0c135b9427e7` README only; PR1 `5747d684be0e84f54c84c27b8d9a2052336b618d` is old v0.4 docs. PR body explicitly says v0.6/24-test implementation is offline/unpushed. It is unavailable, not reused or integrated.

## File-level reuse

- PR64 `web/research_contract.py`: exact AST/function extraction of `PredictionError`, `_number`, `plackett_luce` into `race_ai/legacy_boat_rank.py`. No betting/provider dependency. Six-boat output parity test; N-participant adapter retains the conditional PL formula, enumerating only top-three for larger fields.
- PR64 `race_ai/prediction.py`: reuse immutable INSERT/original-first receipt and result-revision design. Its six-boat/result/start-time coupling prevents wholesale reuse for sales-cutoff multi-sport records. New synthetic journal adapts those boundaries; not a production replacement.
- `official_day_schedule.py`, `national_day_pipeline.py`, `official_racelist_adapter.py`, `official_racelist_worker.py`: existing bounded boat/date/scope parsing, rights before I/O, no-event vs failure. Dependencies include core, archive/B-snapshot parsing, Tokuyama transport and source rights. Defer actual adapter until purpose grants and current cutoff mapping.
- `official_observation_store.py`, `day_feed_store.py`, `feed_worker_handoff.py`: existing versioned observations/atomic local handoff/private publisher/archive paths. Real cross-run external persistence/time attestation remains separate; do not treat this SQLite simulator as that proof.
- `name_bound_result_source.py`, `venue_result_reconciliation.py`: preserve official identity/refund/revision semantics; not generalizable by replacing boat count alone.
- `money.py`: preserve exact payout/refund accounting, not imported into the ranking path.
- `model_training.py`: market-derived feature is selectable in `_feature_names → _record → scaler/matrix → _fit → validation/model bundle`; exported `uses_odds` is tracked. This is a reachable legacy offline API, not evidence it trained deployed forecasts. The new unit neither imports this trainer nor loads its model artifacts. Fixed synthetic model/feature allowlist prevents its admission; legacy feature definitions/history are unchanged.
- PR64 workflows and all old provider/media/decode assets remain unmodified. No full 1141-test legacy rerun without code change.

## Minimal dependency route

main README → extracted pure ranking kernel → sport/snapshot adapter + synthetic journal → credential-free synthetic hosted workflow.
No stack-wide merge/rebase/force-push. Future real collector → authenticated external immutable writer → independent persisted-time witness must be separately admitted.
