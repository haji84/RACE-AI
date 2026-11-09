# BOAT全モデル接続監査 / 2026-11-10

## 検査範囲と証拠の限界

基準はPR71 `064bc0609331e3b86b98ac80ca2e55743fea30d8`。修復は隔離ブランチ `fix/boat-all-model-recovery-20261110` で行う。以下は実コードの静的接続調査であり、当日の実予想・私有重みの復元・締切前の外部保存・実績改善を証明するものではない。

`existing_model_coverage.active_catalog()` は全競技15系統、うちBOAT適用14系統。`catalog()`の旧16系統をそのまま稼働分母にしてはいけない。販売者モデル `seller-shadow-v1-20261104` は退役、オート専用モデルはBOAT対象外。14という数字は基本モデルの系統数であり、学習版・映像版・別PRの研究版を含む全バージョン数ではない。

追加確認: `race_ai/*.py` のトップレベル MODEL_ID / MODEL_IDS / BASELINE_ID / CHALLENGER_ID / LEARNED_ID / MODEL のリテラルをASTで走査した。台帳外はsixway凍結スキーマと音声認識器の識別子。音声認識器を予想モデルに数えない。この走査だけでは動的なID・全過去ブランチ・外部端末の原本まで網羅したとはいえない。

## 基本モデルごとの接続表

表中のパスは `race_ai/` 配下。P0は展示前、P1は展示後。P0/P1対応は入力契約であり、当日の実行成功を意味しない。版はコードに記載されたものだけを示す。独立したmodel_versionがない場合はnullを保ち、推測で補わない。

| モデルID | 実装と実行入口 | コード上の版 | 時点 | 主な必要入力 |
|---|---|---|---|---|
| boat-display-rating-PL-reference-v1-UNVALIDATED | boat_ab_shadow.build_pair | 別版なし | P1 | 同一レースの出走表・展示、登録番号、取得時刻 |
| boat-course-motor-shadow-v0.1-UNTRAINED | boat_ab_shadow.build_pair | 別版なし | P1 | 同上、モーター率・コース |
| boat-local-start-course-shadow-v0.1-UNTRAINED | boat_live_feature_shadow.build_live_feature_shadow | 別版なし | P1 | 当地率・平均ST・展示ST |
| boat-course-entry-method-scenarios-v0.1-UNTRAINED | boat_tactical_scenarios.predict_tactical_shadow | 別版なし | P1 | 時点以前の進入・コース・決まり手履歴 |
| boat-comprehensive-v1 | boat_multi_feature_models.run_models | 0.1.0-UNTRAINED / 0.2.0-SPARSE-UNTRAINED | P1、疎入力P0 | 能力・近況・モーター・コース・ST・条件、欠測理由 |
| boat-scenario-mixture-v1 | boat_multi_feature_models.run_models | 0.1.0-UNTRAINED / 0.2.0-SPARSE-UNTRAINED | P1、疎入力P0 | 同上。別のnative計算結果を保存 |
| boat-observed-pairwise-factor-v1 | boat_observed_pairwise_models.predict_pair | 0.1.0-UNTRAINED / 0.2.0-ACTIVE-ROSTER-UNTRAINED | P0/P1 | 認証済み観測、参加艇、原本SHA、欠測 |
| boat-observed-pairwise-start-v1 | boat_observed_pairwise_models.predict_pair | 0.1.0-UNTRAINED / 0.2.0-ACTIVE-ROSTER-UNTRAINED | P0/P1 | 同上、ST観測 |
| multisport-factor-interaction-v1 | four_sport_model_suite.run_suite / comprehensive_four_sport_models | 0.1.0-UNTRAINED / 0.2.0-SPARSE-UNTRAINED | P0/P1 | 選手特徴・環境・出典時刻、疎入力契約 |
| multisport-scenario-ensemble-v1 | four_sport_model_suite.run_suite / comprehensive_four_sport_models | 0.1.0-UNTRAINED / 0.2.0-SPARSE-UNTRAINED | P0/P1 | 同上。固有のモデル出力 |
| multisport-conditional-duel-v1 | four_sport_model_suite.run_suite / four_sport_matchup_models | 0.1.0-UNTRAINED / 0.2.0-SPARSE-UNTRAINED | P0/P1 | 同上。対戦関係 |
| multisport-race-trajectory-v1 | four_sport_model_suite.run_suite / four_sport_matchup_models | 0.1.0-UNTRAINED / 0.2.0-SPARSE-UNTRAINED | P0/P1 | 同上。展開特徴 |
| multisport-chronological-ranker-v1 | four_sport_learning.forecast | 復元した学習物のmodel_versionを保持 | P0/P1 | 正規の学習物と時点の合うsnapshot。未学習ならTRAINED_ARTIFACT_MISSING |
| boat-pdca-lane-shadow-v1 | existing_model_dispatch._execute → scripts/existing_pdca_offline.mjs → workers/boat_pdca_shadow.mjs:buildChallenger | 別版なし | P1 | 過去の同場24結果以上と今回の事前入力 |

### 上記14系統の共通経路

- 入力変換: `race_ai/boat_all_model_inputs.py:build_native_inputs`。
- 呼出し: `race_ai/existing_model_dispatch.py:dispatch`。1グループの戻り値をモデルIDごとに取り出し、元計算の出力・ハッシュを保持する。別名コピーでモデルを追加しない。
- 展示前: `scripts/boat_all_model_cycle.py:bootstrap_current` → `race_ai/boat_all_model_cycle.py:forecast_saved_p0`。入力契約上不可能なP0を無理に予想させない。
- 展示後: `.github/actions/existing-model-round/action.yml` → `prepare` → 同じ公式取得 → `generate` → `forecast_round` → 既存dispatch。
- 保存: `boat_all_model_store.seal_forecasts` → 暗号artifact → 独立`readback` → `state/boat-all-model-forecasts`。入力・学習物の復元元は `state/boat-model-runtime`、原本長期保全は `state/boat-private-originals`。
- 表示: `dispatch_product_projection.project_dispatch`、`boat_all_model_cycle.project_round`、`scripts/boat_saved_view_feed.py`、`web/product-data.js`、`web/existing-model-catalog.js`、`web/app.js`。台帳掲載と保存予想ありは別判定。
- 結果・PDCA: `racer_result_bridge` / `model_pdca_history` と既存 `verified_bulk_backtest.settle`。学習対比較は既存 `all_existing_model_cash_pdca` を使う。新しい採点器を追加しない。

この呼出しコードは既に存在する。ワークフローやactionの表示名にfive-model/A-Bと書かれていても、実コードは全モデル経路を含む。名称だけを見てA/Bだけが接続済みと断定しない。一方で本番mainの定期起動からこの予想一巡が走った証拠は今回未取得。

## 台帳外の版・研究経路を別管理する

| 対象 | 実装・入口 | 保存／照合と未解消事項 |
|---|---|---|
| 基本14系統の学習パラメータ版 | all_existing_model_registry / all_existing_model_learning.forecast_pair / all_existing_model_runtime.generate_current_pairs、github_existing_cycle._all_model_research_generate | 既存all-existing-model-pairs暗号artifact、venue-research-readback・venue-research-pdca。元版と学習版は同じmodel_idでも学習SHA・版・入力SHAを別管理。学習物未復元を接続成功にしない |
| 観測相性2系統の学習版 | observed_weight_learning.make_shadows、0.2.0-FITTED-SHADOW、ACTIVE-ROSTER版 | 既存P1・result archive経路。新しい原本の事前保存証明は未検証 |
| 観測相性2系統の映像学習版 | boat_video_learning、0.3.0-VIDEO-EXPERIMENTAL、boat_video_forward.fit_matched/register_study/forecast/score | P1の独立した映像文脈・学習版・開催分離が必要。基本14系統とは別に版を追跡。今回の実映像入力・予想・読戻しは未実施 |
| 44要素・120通りのsixway研究版 | boat_six_way_probability_overlay.cjs:predict、boat_post_exhibition_ab_handoff.prepare_round | 44個の予想モデルではない。既存暗号P1に同梱する研究版。厳密なsame-race入力、真正な凍結係数、進入証拠、予選情報が必要。private prepared inputがないとHOLD |
| PR108の44要素入力橋渡し | PR108 HEAD cdc099965fc3d5dfea581478d6e0aa26f97a968d、race_ai/boat_44_p1_input_bridge.py、scripts/boat_44_p1_private_predict.cjs | Draft未統合。専用CLI作成は本番接続やAES読戻しの証拠ではない。PR71の上記prepared input経路へ結合するレビューが残る |
| PR64の旧原本・比較経路 | 固定参照761247bee0209e37b1af6b8885e92cad3e9260a5 | パーサー依存・歴史原本として維持。旧版を現役へ自動昇格しない。全過去版の物理保存先の網羅は未証明 |

## 今回の原因と修復

`prepare_round` が `create_candidate` に渡すbaseline外側へrace_idを入れていなかった。fixtureも同じ欠落があり、厳密な照合でPOST_EXHIBITION_AB_RACE_IDENTITY_MISMATCHとなった。fixtureを直すだけでは実際のroundの候補数0が残り、本体の渡し忘れも修正した。レース一致・締切・原本SHA・進入証拠の検査は緩めない。外側ID欠落/不一致、内側予想ID不一致、文脈ID不一致の拒否回帰を追加。

この修正は全14系統の本番復旧そのものではない。実際の全モデル接続完了は下記がすべて揃ってから判定する。

## 本番切替の未達条件

1. 同じ最新HEADの必要な全CI成功とCODE変更の安全確認。対象テストの合格を全CI合格にしない。
2. 既存source-owner境界の正式解除・同時writerなしの確認。`docs/RACE_AI_LATEST_STATUS.md`のCODE専用許可をprovider取得の解除へ読み替えない。
3. 本番mainの既存自動起動と、上の全モデル・各研究版の必要入力供給。既存の取得担当・writer・原本・権限を増やさず接続する。
4. 実開催台帳×適用モデル×対応段階×正規の版に対し、予想なしの理由を全件記録。INPUT_MISSING、TRAINED_ARTIFACT_MISSING、UNCONNECTED_NATIVE_RUNTIME、INPUT_REJECTED、期限超過は区別する。現dispatcherに汎用のEXECUTION_FAILED状態がない点は未解決の診断差分として残す。
5. 実データ→各native出力→事前暗号保存→独立読戻し→モデル別表示→公式結果→既存PDCA。投資・払戻・返還・収支・回収率・累計損益を同一race/stageで比較する。実購入不明なら仮想購入と明記。

本監査で新しい予想、モデル係数、公式取得、所有者鍵の取り出し、本番デプロイ、原本の上書き、投票は行っていない。1ケースの成功を全日・全モデル完了へ換算しない。
