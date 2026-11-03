# RACE-AI 既存ボート予想方式の正本照合とPR64→PR71接続（2026-10-24）

対象：[Issue #67](https://github.com/haji84/RACE-AI/issues/67)、旧要件[PR #61](https://github.com/haji84/RACE-AI/pull/61)、K/B・履歴[PR #64](https://github.com/haji84/RACE-AI/pull/64)、高度モデル[PR #71](https://github.com/haji84/RACE-AI/pull/71)、接続テスト[PR #72](https://github.com/haji84/RACE-AI/pull/72)。

## 1. 正本の優先順位
1. 最上位GOAL・全対象分母・予想点数・オッズ遮断・権限方針：Issue #67に記録された採用要件。
2. 詳細な予想要因と公式データ仕様：PR #61の53章および修正追補。**設計要件であり稼働済みコードの証拠ではない**。
3. 既存ソース/予想の実装：各Draft PRの実コード。PR #64のK履歴/ST実コース・展示/正本SQLite、PR #71の総合モデル・展開モデル・条件付き着順モデル等。
4. データの検証・シャドー比較：PR #72。今回の3指標B-LITEは「旧コードの代わり」ではなく**限定比較用ベースライン**。
5. 旧版との差分と競合は未承認main統合で勝手に解消しない。Draft PRを積み重ねた状態からの一括統合はしない。

## 2. 予想因子別の実装・接続監査

| ユーザー採用の予想要因 | 仕様正本 | 実装が存在する場所 | PR72からの実データ受入状態 |
|---|---|---|---|
| 出走ID、艇番・登録番号・モーター番号、B日別統計 | #61 / #67 | #64 `core.parse_b`、`official_b_snapshot_adapter.program_details` | **公式実B 14場×168R・1,008艇解析成功**。3種類の数値候補抽出済。元の公表時刻・母数・目的別権利は未受入 |
| K過去着順・同コース実ST直近5/10/20 | #61 / #64 v0.7 | #64 `core._asof_rows`, `histories`, `racer_history_bridge` | **実装済みだが本番PR71へ未接続**。新bridge `from_pr64_imported_K` は既存SQLite revision-aware readerを呼び、出典ハッシュ・as_ofを保持。合成で接続確認、実K母数と発表時刻は未実証 |
| 近走成績、STのばらつき | #61 / #71 | #71 `boat_feature_adapter._historical_past` が5〜30走を評価 | 本工程でPR64 K形式から`last_races`へ変換し、PR71既存アダプタを再利用。F/L・欠場・不明はゼロ補完禁止 |
| 展示ST・展示タイム、オリジナル展示 | #64 v0.7 / #61 | #64 `core.save_exhibition`, `exhibition_asof`、#71 `boat_feature_adapter` | スキーマと時点付き保存は存在。全6艇のリアルな利用可能/承認済展示入力がないため実予想ブロック。動画からの行き足/旋回の完全自動実測は未達 |
| モーター2連対率・機歴・整備 | #61 / #64 | #64 B詳細統計、motor history等、#71 motor rating | B単発の率は候補取得。モーター番号・使用時期・直近整備等の長期連結と効果学習は未証明 |
| コース/枠/実進入、前付け・被前付け・深イン | #64 v0.7 | #64 同コース履歴/entry evidence、#71 `boat_multi_feature_models._scores` の`lane_prior` | **PR71総合・展開は枠priorを考慮可能**。進入前付け攻防を実映像で識別して展開確率に供給する経路は設計段階 |
| 天候・風向風速・波・水面 | #61 / #71 | #71 `boat_multi_feature_models._scores` のweather context、#71四競技シナリオ | 予測モデルコードは存在。実観測の公表時刻・予報対象時刻・会場条件・利用権限を揃えたデータ供給は未実証 |
| 1着仮説ごとに2・3着を条件付き評価 | #67 / #71 | #71 `four_sport_matchup_models._ordered_distribution` | 合成テスト済の研究アルゴリズム。実75観測スロット全件を満たす前時点の承認済snapshotが無くリアル入力未接続 |
| 予想最大8点・全120通り・個別の根拠 | #61 / #67 | #71 `boat_multi_feature_models.run_models`、`four_sport_model_suite.run_suite` | 合成テストで稼働。実全数の事前保存・モデル別入力/寄与の画面連携は未完成 |
| 予想凍結・公式結果改訂/返還・PDCA | #67 | #64研究用immutable store、#71 UI、#72証拠/凍結監査 | 2レースの**非正式研究シャドーのみ**締切前GitHub保存。正式入力承認・結果訂正照合は未達 |
| B-LITE (3指標比較基準) | #72 | #72 `boat_sparse_shadow_models` | 実B単発の暫定研究プレビュー。**高度モデルの代替として本番採用しない** |

## 3. 今回実際に接続したコード

- **再利用のみ、新しい予想アルゴリズムを増設していない**。
- `race_ai/boat_existing_asset_integration.py` はPR #64の `core._asof_rows` をそのまま呼ぶ。Kの最新有効revision・ST状態・着順・出典hashを保持して、PR #71 `boat_feature_adapter._historical_past` の実入力形`last_races`へ変換する。`st_status=F/L/MISSING/ABSENT`と未確定着順、当日以後の結果、未来の訂正、過小サンプルは捏造せず除外する。
- 同モジュールの `build_readiness` がK履歴/モーター/展示/風波の入手可能候補数と不足箇所を6艇別に列挙する。**構文的に値が揃った事実と、正式に用途権限を得た事実は別**。
- 必要な出典・刊行時刻・独立した利用許可が揃う場合に限り、`run_pr71_existing_multi_models` がPR71の`boat_feature_adapter.from_approved_features` と `boat_multi_feature_models.run_models` を**直接呼ぶ**。モデル式・係数はPR71のまま。合成6艇の全120通り×2モデルを通すテストを配置。
- **監査で見つけた既存の問題**：PR71 `boat_feature_adapter` はBスナップショットの`first_observed_at`を元発表時刻`published_at`として転用する。観測が元発表を証明するわけではないため、`run_pr71_existing_multi_models` は独立した元発表時刻の確認が無ければそのまま呼ばない。ソース権限チェッカーもデフォルト拒否。
- PR64の`provenance.verified_official=0`の構造保存を、外部認証済み・学習許諾済み証拠と混同しない。実K/Bの自動取得を今回増やさない。

## 4. 次に突破するステージ（順番を変更しない）

1. **実Kに関する時点と取得方針**：公式日別Kを許容される方法で取得した場合、PR64の最新revision付き着順・STの母数を歴史的実サンプルで調査。出典公表/収集時刻とsample_nを詰める。Kの過去成績を当該レース結果後に作って予測したことにはしない。
2. **PR71アダプタの日付契約修正案と独立レビュー**：`original_published_at`と`first_observed_at`を別フィールドへ改修する提案を先にレビュー。元の予想本体を過去レース後に勝手に変更しない。
3. **展示＋風波の前時点観測**：6艇分が実レース締切の前に揃うか測定、未観測・未許諾・未公表を明記。架空のST=0、良走路等を補完しない。
4. **同じ未来レースで既存高度モデルを直接実行**：旧B-LITEは比較基準としてSHA固定、PR71総合/複数展開/条件付き着順の独立予想Top8と、モデルが実際に使った特徴量・展開・不採用理由を別記録。全対象レースで欠測/未予想を分母から消さない。
5. **公式結果**：予定時刻でなく正式締切前のGitHub等外部保存レシートと原本の読戻し、公式決着/返還/払戻の改訂履歴を照合して初めて正式Hit@8に計上。結果を見て過去8点を変更しない。

## 5. 未達と安全

現時点の統合テストは**架空K/B/展示/風波入力**。元データ自動取得・実レースモデル実行、別AIによる批判レビュー、本番への権限/費用・外部公開、main統合は行っていない。98%は未達・根拠のない保証はしない。Draft PR #61/#64/#71/#72は未統合のまま。

## 2026-10-24 追記：モデル本体の再利用テストまで実証

- **PR64 Bの元データ形状→PR71出走者入力**：`pr64_B_to_PR71_racelist(entries,details,deadlines,...)`を追加。6艇のID、B数値、モーター番号、予定締切を厳密結合し、`first_observed_at`を実測キャプチャ時刻とし`source_original_published_at=null`、`original_publication_verification=false`で渡す。**元刊行時刻をキャプチャ時刻で偽装せず、未検証のままならPR71推論を実行しない**。証拠がないBファイルでも候補レコード数と欠落を可視化できる。
- **PR64 Kの既存DBリーダー**：`from_pr64_imported_K`は新しい歴史パーサーではなく、PR64 `core._asof_rows`（訂正履歴の最新版と時点フィルタを処理）をそのまま呼び、`provenance`表のK種別、原文SHA、公開/取得時刻との一貫性を確認する。
- **PR71既存の総合/複数展開の2モデル**：`run_pr71_existing_multi_models`がPR71の`boat_feature_adapter.from_approved_features` → `boat_multi_feature_models.run_models` をそのまま呼ぶ。候補全120通りと最大8点を別々のモデルで計算し、研究のみ、正式凍結とはしない。
- **既存モデルの予想根拠**：`explain_existing_PR71_boat_score`はPR71の実`_scores`から6艇それぞれの総合・先行・攻撃・荒れ展開の内部得点とシナリオ混合係数を読み出す。新しい重みを捏造しない。因果説明や実測確率への校正を証明するものではない。
- **PR71条件付き着順を含む4モデル**：`run_PR71_existing_all_four_model_families`が`four_sport_model_suite.run_suite`を直接呼ぶ。元の75観測スロットを満たせない場合は**モデルの既存strict validatorで失敗する**。既存モデルを勝手に3指標化しない。これらはPR71のコード版へpinした合成データの試験であり、未来レースの実運用成績ではない。

### Exact-head CI
- [GitHub Actions #40055920498](https://github.com/haji84/RACE-AI/actions/runs/40055920498)：head `e54963a61bde8b5837001df11f0db2beadc99dc1`、**completed/success**。
- Python通常回帰 **188 tests PASS（実checkout未配置の相互参照テストはskip）**。後続の明示的にPR64 `761247bee0209e37b1af6b8885e92cad3e9260a5`とPR71 `39d888329d18a5ed517de7c6b25ae3ca52257255`をcheckoutした接続試験で、**12 tests PASS、必要なPR64 SQLite K読戻し・PR71総合/シナリオ2モデル・四競技共通の条件付き着順4モデルの実コード呼出しを確認**。全て架空レースの模擬データ。
- PR61/64/71/72の本体モデル・旧予想SHA・重み・main、費用/権限/一般公開を変えていない。

### 未達の正しい読み方
**既存の高度な数式を直接呼べることは合成テストで確かめた。しかし実B＋実K履歴＋当日展示＋当日風波＋許諾を揃えて高度モデルを未来レースで確定できたわけではない**。現行の長期ST/展示/気象の真の欠測はそのまま保持し、必要情報が揃わない対象レースは未予想として分母に残す。
