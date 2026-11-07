# 既存モデルの実データ学習・前向きPDCA進捗（2026-11-07 JST）

最新の実学習は **BOATの12枠**。A/B・C-liteを加え、独立した締切前保存と通常確定結果を確認した同じP1の8レースで、全12枠を学習6・holdout2に分けた。暗号化候補の独立復元も確認した。[実件数と保持pointer](evidence/2026-11-07/twelve-native-model-learning-counts.json)。残る **19枠の実学習は未完了**。以下の9枠の三国1R実未来PDCAは以前の候補の証跡であり、新12枠の未来成績へ流用しない。

JRA公式の実出馬表16件と、即PATの「土曜全レース・発走1分前」規則を取得し、原HTTPメタデータとともに所有者キーで暗号化・別復元した。実16件の変換は10 READY・6 HOLDで、過去走のない馬などを架空値で補わない。これは出馬表取得と入力変換の実確認であり、競馬5枠の学習完了・予想保存・結果照合ではない。既存Actionsに一度だけ実native入力を凍結する処理を追加した。実行結果・保存証拠は確認後に追記する。

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

## 7. 以前の9枠候補で未完了だった22枠

下表は9枠候補時点の記録。最新P1候補ではA/B・C-liteの3枠が実学習済みとなり、未完了は19枠である。

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

欠測表記修正まで含む全体成功済みの実装HEADは `86e6f13e25d1af964bae471c37b28d0e8bbf621d`、[Actions 42316299401](https://github.com/haji84/RACE-AI/actions/runs/42316299401)。全Python2,575件・失敗0・170 skip、隔離video283件、Node88件と76件、画面検証を通過した。検査の重複を独立実レース数として合算しない。追加17件のfocused検証も成功。[機械可読の検証記録](evidence/2026-11-07/native-model-learning-final-verification.json)に固定する。前の実装7b4f672も[全体成功](https://github.com/haji84/RACE-AI/actions/runs/42313951152)。報告文書だけを追加した最新HEADと最終ChecksはPR71と作業最終報告に示す。

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

新モデル、新workflow/schedule、新クラウド、Cloudflare/Vercel、課金、main統合、公開原本、自動投票、本番昇格は追加していない。公式取得ワーカーの上限と同時実行条件を維持する。PR検証はHEAD別の実行単位とし、既存の暗号化artifact読戻しジョブに `actions: read` を明示した。全22枠の実学習と未来PDCAの証拠が揃うまで、依頼全体を完了扱いにしない。

公開可能な実測件数・SHA・保存ポインターは [nine-native-model-learning-counts.json](evidence/2026-11-07/nine-native-model-learning-counts.json)。学習係数値・入力原本は含まない。

## 13. 実未来9枠の締切前保存チェックポイント

下表は締切前保存を確認した時点の記録。通常確定結果とPDCAの完了記録は次節に示す。

2026年11月7日三国1R（競走場コード10、08:47 JST締切）について、会場別履歴を含む同じ元観測から9枠それぞれのnative入力を作り、元モデルと学習候補のP0予想を暗号化した。展示情報はP0の欠測のまま保持し、新予想の実作成時刻と保存時刻を記録した。

| 項目 | 実確認値 |
| --- | --- |
| code HEAD | `8d956e978abe98eedac9d53eb4bb44c55d451b9f` |
| Actions run | [42312703008](https://github.com/haji84/RACE-AI/actions/runs/42312703008) |
| 予想artifact | `13549117749`、`all-existing-model-pairs-42312703008-900001` |
| GitHub保存時刻 | `2026-11-06T23:35:56Z`（11月7日08:35:56 JST） |
| 実締切 | `2026-11-07T08:47:00+09:00` |
| training SHA256 | `3ea27d5c7709fd51e8a980bce2497ee5a3332760236145624d279ee83e392768` |
| ZIP SHA256 | `db35c80074a8a26c7ffd51f93a0f39afaf3fb390146169c1e6321945bd13abbd` |
| 独立読戻し | 実APIメタデータ・実所有者キーで9枠、1レース、P0、同一名簿・実締切を再確認 |
| 原本の追加保持 | 既存暗号化transfer ref、commit `f7ae24e0ffae7b92ec7d766053a4e8b94d98bcb9`、保存バイト一致 |
| 新しい提供元アクセス | 0。保存済み公式P0原本・暗号化runtime・会場別gridを使用 |
| 確定結果・PDCA | このチェックポイントでは結果待ち |

実保存の集計は [future-save-counts](evidence/2026-11-07/nine-native-model-future-save-counts.json)、原本保持は [future-source-retention](evidence/2026-11-07/nine-native-model-future-source-retention.json)。同じレースのP1予想や旧2枠候補の評価とは区別する。

P0は番組情報だけを用いる入力区分で、実際の展示実施・公表前だったことを意味しない。保存済み9枠の欠測ラベル `NOT_YET_PUBLISHED` は古い番組原本由来で、新予想時点の公表状況を再確認した証拠ではない。原本は変更しない。以後の新生成だけ、観測系・共通入力は `MISSING`、full入力は `NOT_AVAILABLE` とし、`publication_status_checked=false` を記録する。9枠の入力数値・欠測マスク・全120順位/確率が変更前と同一であることを検証した。保存済み予想や当該PDCAの数値を修正した扱いにはしない。

実行時には4.47MBの当日原本が汎用JSON読込の4MiB制限に達してHOLDした。原本用の既存8MiB runtime契約へ接続し、実132レース原本の再読戻しと、4MiB超・8MiB超・重複キーを含む10件のCLIテストで確認した。汎用4MiB制限は維持した。別のCIでは完全なSHA内の数字列を選手番号と誤認するテストを修正し、公開データの構造・完全なSHA・私有項目不在を検証する。全体ローカルsnapshotは2,562件・失敗0・112 skip、追加のRESULT保持検証20件も成功した。最終固定HEADの全CI結果は別途記録する。

非BOAT原本は、ユーザーの依頼に従いGitHubの108ブランチ先端、ローカル1,799 commit object、関連15 Actions runを実確認したが、適格な実native原本は0件だった。[調査報告](GITHUB_NONBOAT_ORIGINAL_RECOVERY_20261107.md)に範囲と限界を記録した。合成KEIRIN暗号文、SHAのみの記録、未取得の試走、原本を保存していない検査は実学習に数えない。

## 14. 通常確定結果との実未来PDCA完了

三国1Rの公式観測は08:53:12と08:58:18 JSTには `OFFICIAL_RESULT_PAYOUT_ONLY` だった。払戻だけから本人名簿や通常確定着順を補わず、09:05:08.567888 JSTに取得した `AVAILABLE` の通常結果で、6人の登録番号、レース識別子、実締切、確定着順・払戻の条件を検証した。これは取得で観測した時刻であり、公式公表時刻や実発走時刻の独立確認ではない。

結果artifactは `13549429995`（run `42289399740`、code `ad220c84eb4ff86b9f00dbab4d6246c4d08190b2`）。実GitHubメタデータを再取得し、08:35:56 JST保存の予想artifact `13549117749` と結合した。**1レース・9枠・元モデル9予想/学習候補9予想・通常確定9ペア**を採点。pendingや特殊結果を通常の外れへ変換していない。

09:11:57.899978 JSTまでに、元予想9 partition・PDCA9 partitionを既存refへ暗号文のまま保持し、18件を別読戻しで認証・再計算した。元ZIP2件も実メタデータとともに保持・独立復元し、元バイトと一致した。RESULT ZIPはRACE-AIの結果観測ジャーナル・関連保存物であり、提供元HTML原文を保存したという意味ではない。

同じ出力先への実再実行は `OUTPUT_EXISTS_DO_NOT_RESET` で二重処理を拒否し、成功報告を含む155ファイルのSHA集合が不変であることも確認した。これは既存の成功結果を取り消すHOLDではなく、再実行による原本上書き・件数増加の防止確認である。

- [実PDCA件数・保持pointer](evidence/2026-11-07/nine-native-model-future-pdca-counts.json)
- 元予想ZIP SHA256：`db35c80074a8a26c7ffd51f93a0f39afaf3fb390146169c1e6321945bd13abbd`
- 結果ZIP SHA256：`365838c44a98fe96b5c0b41f9b438cc02011aba81a99e5b3d5203b91f9a174cd`
- 元予想/結果の保持commit：`d9628e2c28e5160145d59df14c6a46ad22c5e76b` / `f15bbb1882de919a272e9c4ad85f14093b143ca2`
- 18 partitionの保持pointer集合SHA256：`a9551f74a76c061e2acc5e829ebe9d7f5895473ac5a6e0a5aff70105c0390e3c`

各枠のlog loss差・native買い目差に基づく次回検証候補も、結果後の研究記録として暗号化・独立復元した。[改善検討の件数とpointer](evidence/2026-11-07/nine-native-model-next-review-counts.json)。同条件の前向き標本追加、係数の支持・欠測の再確認、実展示/STを使うP1の別コホート検証、原文保持と公式日次K公開後の再照合を候補にした。元予想や学習係数は変更していない。1レースの改善・悪化から精度向上や本番採用を結論しない。

凍結入力の[実特徴量カバレッジ](evidence/2026-11-07/native-model-future-feature-coverage.json)も別に確認した。全国勝率・モーター2連率・コース平均STは各6人、コース平均着順は5人にあり、残る1人は未解決の結果状態を理由に欠測を保持した。直近平均着順/直近平均STと展示タイム/展示STは、今回の6人入力では全員欠測だった。入力契約が接続されていることと、全項目の実取得を混同しない。

## 15. 指定12項目の作業報告

| 項目 | 確認内容 |
| --- | --- |
| 1. API一覧 | [艇愛API仕様と過去の実取得](TEIAI_HISTORY_INTEGRATION.md)のmeta/highpayoff/today/stadium-course/race/racer/racer-results/rank-nextを再利用。今回の追加学習は保存済み公式B・会場別grid、未来結果は既存Actionsの公式raceresult観測。追加の艇愛API取得は0件 |
| 2. 実取得・使用項目 | 今回の未来入力は登録番号/艇番/開催日・場・R・締切と、全国勝率/モーター2連率/コース平均STが各6人、コース平均着順5人。実履歴の母数・期間・出典を保持。直近2項目・展示2項目は各6人とも欠測。未来結果は6人の通常確定着順、3連単払戻、結果状態・取得時刻・source SHA。未使用の氏名等をモデル特徴量へ自動追加しない |
| 3. 不足項目 | 非提供の全国/当地3連率、完全な1997〜2004一括原本、未報告日、実発走・独立公表時刻、提供元HTML原文・訂正前後の全原本、非BOATの本人ID付きnative原本等。P0の展示/ST・天候等を推測しない |
| 4. 正確性と件数 | 過去の艇愛対公式Kは2レース・延べ8行/独立7出走、レース49非欠測項目・CSV17項目・払戻10組番が一致した限定標本。今回の未来照合は1レース・6登録選手・9枠であり9独立レースではない。全件精度100%や全訂正追跡を主張しない |
| 5. 接続特徴量 | 過去履歴、場/過去実進入コースの成績・ST、直近成績、母数、既存native式で定義した全国勝率・モーター指標、疎入力mask/lineage。9枠の原式と係数語彙を維持。93座標rankerは支持された15座標だけが今回更新 |
| 6. 新規・変更一覧 | [学習接続の変更ファイル一覧](evidence/2026-11-07/native-model-learning-changed-files.json)。PR71の全Filesには並行する別変更も含む |
| 7. テスト | 全体snapshot2,562件/112 skip成功。最終実装86e6f13のActions全Python2,575件/170 skip成功。追加の入力・原本・JSON上限・出典・欠測label/9枠同値・RESULT保持のfocused検証を実施。合成31枠試験と実9枠を区別 |
| 8. Actions URL | [最終実装の全体成功42316299401](https://github.com/haji84/RACE-AI/actions/runs/42316299401)、[実未来予想生成42312703008](https://github.com/haji84/RACE-AI/actions/runs/42312703008)。後者の予想ジョブ・実artifact保存は成功し、全体は後段viewerの旧12分制限でcancelled。現行は同じviewerジョブを15分とし、検査を省略しない |
| 9. HEAD | 実未来予想は8d956e9、欠測表記修正まで含む全体成功の実装は86e6f13。最新報告HEAD・Checksの実状態はPR71および最終回答に固定して記載 |
| 10. 実データ動作 | 実8レース×9枠を学習6/holdout2でfit、所有者キーで暗号化・復元。実未来三国1Rで同一元観測→native9枠→締切前保存→通常結果→9枠PDCA→18件と元ZIP2件の独立復元→改善検討記録まで成立 |
| 11. 未完成 | 実学習は残22枠（BOAT6、KEIRIN5、AUTO6、HORSE5）。非BOAT原本はGitHub調査で回復0件。必要なnative8レース/枠、原文・公表/訂正の全履歴、将来の十分な評価標本が不足。原本保持・収集済み公開期間・将来性能を混同しない |
| 12. 最小の次工程 | 既存の暗号化保存を再利用し、各未学習枠の本人ID・元入力・実締切・独立保存・通常結果が揃った8レースを確保して同じ6/2学習器へ結ぶ。BOAT A/B/C-liteは既存巡回の未学習入力保持を継続。非BOATは原本の回復または承認済み既存経路での新しい前向き保存から始める。新規定期取得や未知用途の自動スクレイピングへ切り替えない |
