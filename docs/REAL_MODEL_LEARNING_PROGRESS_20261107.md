# 既存モデルの実データ学習・前向きPDCA進捗（2026-11-07 JST）

登録済み16系統・31競技枠のうち、実データで研究用に学習できたのは **BOATの9枠**。同じ独立保存済み8レースを各枠で学習6・holdout2に分けた。残る **22枠は未完了**。未来レースでの新候補の締切前保存、確定結果照合、前向きPDCAの完了はまだ確認していない。

本書は旧来の「実2枠・29枠不足」からの進捗を記録する。全31枠の実学習完了、72異なる実レース、精度向上、本番採用という意味ではない。[実装計画](superpowers/plans/2026-11-07-real-model-learning-completion.md)も同じ区分で管理する。

## 1. 今回の実学習結果

元の観測系2枠×8レースの16レコードに、同じ元入力から明示的に派生した7枠×8レースの56レコードを加え、合計72レコードを使用した。独立レース数は8のまま。元の観測系2枠の係数とholdout指標は以前の候補と一致する。

集計確認元は、担当者が実所有者キーで学習・暗号化・別読戻しを終えた非Git作業領域の `actual-nine-fit-counts.json`。公開するのは以下の件数と検証SHAであり、生入力・選手別値・買い目・学習係数は含めない。

## 2. 再利用した実原本

使用したのは、以前から独立した締切前保存を確認済みのP0観測原本8件と、別取得した確定結果。レースID、艇番、選手登録番号、実締切、元入力SHA、保存時刻、出典SHA・取得時刻を維持する。取得済みの全国勝率、モーター2連率、直近着順/ST、コース別着順/STなどを、既存の観測変換とnative式へ接続した。

今回新しい元データ取得や外部許諾申請を行ったという報告ではない。元原本、認証済み保存メタデータ、公式結果とその訂正履歴を再利用し、過去の原本を書き換えていない。

## 3. 新しい疎入力の範囲

7枠分は、元原本から今回計算した疎なnative入力による研究学習である。未観測の天候、展示タイム、展示ST、完全な潜在ratingを作らず、存在する項だけを元の式で評価し、欠測理由を明示した。P0を展示後P1と呼び換えない。

BOATの疎入力rankerは93座標を持ち、入力schemaと `parameter_contract_sha256` を候補に明示する。公表時刻不明は `None` のまま扱い、実取得・利用可能時刻を検証する。従来のdense catalogとregistry SHA `07da538c97be334845f268a10fb0d7676d3b2cdcd7a3a922b0f7d7d798aaf3f6` は保持する。93座標すべてを推定したわけではなく、支持された15座標だけが今回更新された。

## 4. 実学習9枠の内訳

すべて `sport=boat`、学習6・holdout2。支持数不足の係数はnativeの基準値に固定する。

| model_id | 支持された係数数 | 変更された係数数 |
| --- | ---: | ---: |
| `boat-observed-pairwise-factor-v1` | 6 | 6 |
| `boat-observed-pairwise-start-v1` | 6 | 6 |
| `boat-comprehensive-v1` | 3 | 3 |
| `boat-scenario-mixture-v1` | 9 | 9 |
| `multisport-factor-interaction-v1` | 6 | 4 |
| `multisport-scenario-ensemble-v1` | 6 | 5 |
| `multisport-conditional-duel-v1` | 7 | 6 |
| `multisport-race-trajectory-v1` | 7 | 6 |
| `multisport-chronological-ranker-v1` | 15 | 15 |

係数が変化したこと自体を精度向上の証拠にしない。holdout2件は小さく、全期間・全場・未来性能を示さない。各比較は同じ枠の同じ入力・名簿・締切・結果を使用し、元の正規化、シナリオ混合、相互作用、段階結合、負係数、clampを保つ。

## 5. 派生時刻と元データ利用可能時刻

`all_existing_model_derivation.derive_records()` と `verify_derivation()` は、元原本と派生入力のSHA・名簿・時計・変換を結び付ける。`derived_at` は今回の実計算時刻であり、`derived_payload_saved_before_cutoff=false` を保持する。派生JSONのバイトが当時存在した、当時9モデルの予想を保存した、という主張はしない。

結果の利用可能時刻順に学習6・holdout2を分け、holdoutを係数選択に使わない。学習済みartifactを過去の予想時点に存在したことにせず、後日学習した係数による過去評価は回顧評価として分離する。

## 6. 所有者判断・出典・契約の結合

所有者の個人研究判断は、全入力内容・元原本証拠・派生変換・出典集合・各parameter contractへMACで結合する。再実行ごとに変化する操作時計 `derived_at` だけは安定したintake identityから分離し、その実時刻を暗号化lineageに残す。`source_intake` SHAは実際の原メタデータ全体を別に保持し、別入力への判断の流用を防ぐ。

取得元の利用条件を拡張したことにはしない。既存のBOAT用用途判断を非BOATへ流用せず、本人の個人研究用データの利用を新しい許諾質問で止める運用も追加していない。提供元許諾取得済み、商用利用可、生データ公開可という記録には変更しない。

## 7. 未完了22枠

| 区分 | 未完了枠数 | 必要な実データ |
| --- | ---: | --- |
| BOAT A/B | 2 | それぞれの完全なnative入力と締切前保存・結果の対応 |
| BOAT C-lite | 1 | 元のcourse/start入力と保存証拠 |
| BOAT tactical | 1 | 元の展開・会場・選手履歴と必要な支持 |
| BOAT PDCA | 1 | 対象時点より前の同場24件以上の別レース結果・出典結合 |
| BOAT seller | 1 | 本来の朝版cards/waku、07:00凍結、実締切、登録本人名簿 |
| KEIRIN | 5 | 7/9選手の本人ID付きnative入力・実締切・独立保存・確定結果 |
| AUTORACE | 6 | 共通5枠とpersonal1枠それぞれの実入力・登録選手ID・結果 |
| HORSE | 5 | 馬ID付きnative入力、実出走表・締切・履歴・結果 |

必要な実入力がない枠は未取得として残す。レジストリ登録、合成テストの成功、買い目や事後結果だけを実学習の代わりにしない。最低条件は枠ごとの異なる8レース、学習6・holdout2であり、別モデルの同一レースを水増ししない。

## 8. 非BOAT原本の実探索結果

既存の公開監査メタデータとローカルのファイル名を調べ、さらにGoogle Drive接続で、既知のAUTO20原本名と `keirin_20261103_forecasts.json` の計21名だけを探索した。正確なファイル名filter3回と各名keyword検索21回、**計24回はすべて正常終了・一致0件**。この接続で新しい原本・ラベルは回復していない。ChatGPT Libraryや別保管先に原本が存在しないとは断定しない。

競輪76件の旧bundleはレースIDと買い目・順位スコアであり、native特徴量を再構成できない。AUTOのSHA・private original参照は回復候補で、元入力そのものではない。競馬の既存変換は10頭・22履歴から50観測を得た段階で、必須120観測中70が欠測。いずれも偽のratingや公開時刻で補わない。探索に伴う共有変更、メッセージ送信、購入、ソース許諾の追加要求は行っていない。

## 9. 変更したファイル群と再利用経路

- `race_ai/all_existing_model_derivation.py`、`boat_all_model_inputs.py`：凍結済み実観測からの明示的な疎入力変換、元SHA・実派生時刻・欠測の維持。
- `all_existing_model_{registry,learning,research}.py`、`four_sport_learning.py`、既存native係数adapter：疎入力parameter contract、93座標ranker、実支持に応じた係数固定、元式による評価、所有者判断との結合。
- `all_existing_model_source_derivations.py`、`boat_all_model_cycle.py`：native入力capsuleの凍結、出典closure、既存出力との再検証。
- `all_existing_model_{round_intake,result_intake,intake,receipt,pairs,pdca}.py`、`cycle_recovery.py`：実artifactメタデータ、暗号化FORECAST/RESULT、公式結果・名簿・返還との結合、未取得の明示。
- `scripts/all_existing_model_learning.py`：既存CLIの `--derive-from-observed`、`--native-round-archive-dir`、`--result-archive-dir`。平文結果sidecarによる認証迂回は受け付けない。
- 対応する `tests/test_all_existing_model_{derivation,sparse_learning,cli_derivation,source_derivations,round_intake,result_intake,cli_result_archives}.py` などと本書・実装計画。

既存のモデル、暗号化codec、GitHub保存ref、実artifact reader、通常巡回・結果比較・ローカルSQLiteを再利用する。ここに記載した実装の最終差分は、固定HEADの検証後にPRで確認する。

## 10. 検証済み範囲と最新CIの未確定部分

担当者が確認した全体snapshotは `python -m unittest discover -s tests -q`、**2,489件・440.029秒、OK（112 skip）**。これは実行したsnapshotの結果であり、その後に追加・修正したすべての最終HEADを検証したことにはしない。

疎入力学習、派生lineage、93座標とdense互換、既知公表時刻なしの実capture、元予想の既定SHA、出典closure、native capsule、暗号化RESULT受入、CLI・改変拒否のfocused検証を追加した。最終の正確な対象件数・コマンド・固定HEAD・Actions結果は担当者が検証後に追記する。未取得・pending・特別結果を通常の外れに数えず、合成31枠の試験を実31枠学習とは呼ばない。

**最終HEAD:** 検証後に追記。 **最終Actions run/check:** 未確定・追記待ち。 **最新focused検証の確定件数:** 追記待ち。

## 11. 実暗号化候補と独立読戻し

実所有者キーで学習・暗号化した9枠候補を既存Git状態refに保持し、別読戻しで内容一致を確認した。公開可能な識別子は次のとおり。

| 項目 | 確認値 |
| --- | --- |
| state | `ACTUAL_NINE_NATIVE_CELLS_RESEARCH_FIT` |
| training SHA256 | `b3e16ab35dcd818d86ea929267fef50bd379e2c91de1925fb8fb6b9764f7aaaf` |
| 保存元commit | `7fe3e90ac1c20bfaf5eb4dfab8c6e3f82aa9568b` |
| manifest SHA256 | `08c1fc981d092956c08a98f7cea5c9ec41f8305331c775318e035c257d606b09` |
| 独立読戻し | `OWNER_VENUE_LEARNING_READBACK_VERIFIED`、実9枠一致 |

この保存元commitは暗号化状態の識別子であり、未確定の最終実装HEADや将来runのコードHEADではない。`plaintext_published=false`、`production_promoted=false`、`real_future_pdca_verified=false` を維持する。

## 12. 未来の実運転と残る完了条件

担当者確認時点の既存P1 workerはrun `42289399740`、単発の後続は `42299260917` がpending。既存の08:20 JST開始・最初の08:35 JST締切に向けた経路を変更・再起動していない。これらの旧HEAD runが今回の新capsuleコードや9枠候補を使っているとは報告しない。

残る工程は、最終コードのCIと固定HEAD確認、既存経路への正しい候補読込確認、未来native入力の実締切前暗号化保存、別取得した確定結果の認証、同じ原本に対するモデル別比較・PDCA、未学習枠の8件以上の実入力確保である。データが揃った枠だけ再学習し、未取得・返還・異常・未確定を区別する。

新モデル、新workflow/schedule、新クラウド、Cloudflare/Vercel、課金、main統合、権限変更、公開原本、自動投票、本番昇格は追加していない。既存の取得上限と同時実行条件を維持する。全22枠の実学習と未来PDCAの証拠が揃うまで、依頼全体を完了扱いにしない。

公開可能な実測件数・SHA・保存ポインターは [nine-native-model-learning-counts.json](evidence/2026-11-07/nine-native-model-learning-counts.json)。学習係数値・入力原本は含まない。
