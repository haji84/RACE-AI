# ChatGPT DT-R1 / 独立予想モデルと検証パイプライン

既存の統合モデル、Codexの独立した新モデル、ChatGPT DT-R1を比較するための研究参加モデルです。`haji84/RACE-AI`内で管理し、既存の公式ソース受付、暗号化履歴、レース展開の比較処理を再利用します。

旧版で次工程とした6項目を実行可能なコードにし、固定した実データ30,713レースを取り込んで学習・校正・監査・過去評価まで実行します。**高・激アツを十分な根拠付きで出せる精度、未来の3モデル対戦成績、全国での継続運用は、コードの完成だけでは証明できません。** 実測値と再現条件は[検証結果](evidence/20261128/RESULTS.md)へ記録します。

## 実装した6工程

| 工程 | コード | 実証の状態 |
| --- | --- | --- |
| データ取り込み | data.py、admission.py | SHA固定・読み取り専用SQLite、既存公式受付からの変換。2個の保存DBを実検査 |
| 学習・予測 | features.py、model.py、pipeline.py | 厳密な過去日履歴、条件付き順位分布、ライン依存、候補選択・温度校正。実データ学習済み |
| バンク・タイム・映像 | venues.py、observations.py、context.py、vision.py、phases.py | 公式会場ガイド43ページの形状資料。過去の上がりタイムを学習済み。独立した追加映像・局面ラベルは今回0件 |
| 買い目・信頼度 | policy.py、calibration.py | オッズ別点数上限、1点終了、時系列を分けた校正と監査、証拠不足の保留 |
| 3モデル対戦 | comparison.py、view.py | 同一入力・対象・モデルSHA、欠測込みの集計、日単位の対応付き比較。相手2モデルの実出力は未受領 |
| 継続実行・更新候補 | runtime.py、cli.py、研究用CI | 追記専用原本・結果改訂、既存暗号化codec、復元、再学習候補。正式モデルは自動変更しない |

## 学習内容と計算方法

互換スロットを含む基本の106列は、競走得点、脚質、級班、年齢、ギヤ、取得できた勝率・連対率、ライン、直近5/10/20/30走、同会場・同級班履歴、出走間隔、過去の上がり半周タイムなどです。不明値には欠損フラグを付けます。氏名から公式登録番号を作りません。

外部資料を接続すると互換スロットを含む224列になります。周長、直線、カント、幅員、脚質・ラインとの組み合わせ、取得時刻を確認できる気象、会場別の上がりタイム（最終半周）と独立して観測された区間タイムを扱えます。現在掲載のバンク形状を過去へ適用するときは、明示した研究上の仮定として記録します。最新資料だけで昔の形状が同じだったとは証明しません。

一つの条件付き順位分布から三連単・二車単・全着順の周辺確率を計算します。独立した各着順確率の単純な掛け算ではありません。3〜9車の数学的な処理を検証しています。順位分布は重複のない通常の着順を条件とし、同着・異常終了の確率質量を別途学習したモデルではありません。

実績集計では、有効な上位3着が確定している途中棄権等のレースも含めます。同着が4着以下だけで上位3着が一意な場合も採点します。未出力、欠損、取消、未解決の同着は別々に件数を残します。

### 6局面と映像

`INITIAL → BELL → FINAL_HOME → FINAL_BACK → FOURTH_CORNER → GOAL`を、前局面の順位を条件に学習できます。学習は観測順位、予測はサンプルした前局面順位を使います。観測が足りない局面はHOLDです。ゴール結果から途中の正解を作りません。

局面モデルは通常の着順モデルとは別の研究出力で、物理シミュレーターではありません。サンプル頻度を校正済みの的中確率として表示したり、未検証の局面を本体の確率へ混ぜたりしません。

動画処理は、ローカルフレームの検出・匿名追跡、設定した色域・領域、カメラ切り替え、遮蔽の保留を実装しています。自動検出した物体中心を車輪の通過位置とは扱わず、色だけで選手を断定しません。計測値には、動画・フレーム・選手対応・車輪の位置について別の検証証拠が必要です。画像処理の合成テスト成功は、実映像の認識精度ではありません。

公式の「上がり」は最終バック線からゴールまでの半周です。2026-11-28の所有者指示により、予想のタイム学習は上がりタイムを中心とし、最終1周タイムを除外します。過去の全会場・同会場の上がり平均、件数、欠損、および独立観測の最速・直近・ばらつき等を利用可能です。別途観測された区間タイムは上がりと混同しません。最終1周の旧列は保存済みモデルとの互換用に欠損固定し、学習重みを0に制限します。原本・過去の検証結果と低レベルの観測機能は保存します。絶対速度には対応する実距離と時刻・カメラ校正が必要です。未測定のパワーや疲労をワット・ジュールへ変換しません。

### 上がりタイム相互作用モデル（所有者追加指示）

`agari.py` を学習・CLI予測・shadow runtime・独立原本再構成へ接続。過去の全会場・同会場の上がり平均、相手との差、観測件数、会場差、独立観測の直近・最速・分散を使います。平均秒数が小さい選手ほど相対速度特徴が正になります（物理速度の推定ではありません）。同会場の上がりと脚質・ライン位置・バンク周長/直線/カント/幅員・風向風速/雨等の積、さらにバンク×脚質、気象×ライン位置の組合せを学習対象とします。欠損、未確認の並び、未来の情報は値を捏造せず無効化します。

新規 `study` / `run-candidates` はこの特徴を必ず作り、同じレースと期間で相互作用あり・なしの候補を比較し、選択期間の対数損失でモデルを固定します。上がり履歴単体は比較候補にも残ります。必要なら `--venues` に既存の会場資料、`--timings` に独立観測、`--weather` にレースIDをキーとする時刻・出典付き気象JSONを渡してください。過去アーカイブに真正な当時の時計がないので、同日取得の気象は学習から除外します。公式受付では `weather_records` を既存の独立support verifierに束縛します。気象の新規取得サービスは追加していません。

旧106/224列の凍結モデルはそのまま再現でき、新しい列を持つモデルだけが新変換を通ります。新規の学習済み重み、校正値、実データ改善は再学習後に別途確認する必要があります。既存凍結成績を上書きしません。

## 買い目

基準は、オッズを見る前に固定した「予測確率が最大の1点」のオッズです。

| 三連単の基準オッズ | 上限 |
| --- | ---: |
| 10倍以下 | 2点 |
| 10倍超〜20倍以下 | 4点 |
| 20倍超〜100倍未満 | 9点 |
| 100倍以上 | 12点 |

未指定だった90〜100倍未満は9点側に統一しています。二車単は最大2点です。上限まで埋める義務はなく、追加候補の確率・期待値・目標被覆率に応じて1点で終了できます。人気薄へ基準を後付けで変えて上限を増やしません。

全組番の締切前オッズ、取得元SHA、公開・取得時刻が必要です。欠損・期限後・未検証のオッズなら選択をHOLDにします。期待払戻と投資総額を差し引いた期待収支を分けます。検証済み払戻がない期間の回収率は計算しません。

## 信頼度

| 表示 | 校正後確率の基準 |
| --- | ---: |
| 激アツ🔥 | 90%以上 |
| 高 | 80%以上90%未満 |
| 中 | 60%以上80%未満 |
| 低 | 60%未満 |
| 判定保留 | 独立監査・件数・同条件の証拠が不足 |

これは選んだ買い目集合の的中確率です。モデル・ポリシー・実際の点数・車数・級班などを対応させ、学習とは別の期間で校正し、さらに別期間で監査します。監査の95%区間がラベルの下限を支えない場合も保留です。過去アーカイブの校正を未来の公式運用へそのまま認定移転しません。激アツを増やすために閾値を下げる実装はありません。

## 固定した過去評価契約

| 用途 | 期間 | 登録数 |
| --- | --- | ---: |
| 学習 | 2025-10-01〜2026-06-30 | 20,253 |
| 候補選択・温度校正 | 2026-07-01〜07-31 | 2,416 |
| 信頼度校正 | 2026-08-01〜08-31 | 2,350 |
| 校正の独立監査 | 2026-09-01〜09-30 | 2,186 |
| 過去の最終評価 | 2026-10-01〜11-22 | 3,508 |

ライン相互作用、履歴、外部資料の有無を固定した4候補を、7月の上位3着の同時Log Lossで選びます。最終評価成績を見て候補・閾値を変更しません。ただし、アーカイブ自体は以前の研究でも参照済みであり、未見の未来データとは呼びません。

同日のレースをまとめて変換してから履歴に追加し、同日・当該レースの結果を予測特徴へ入れません。未来運用では、過去日付に加え、元資料と結果それぞれの利用可能時刻を照合します。入力の車番対応、ライン、得点、履歴、外部資料、予測時計もハッシュへ束縛します。

## 実行

Python 3.12、リポジトリのルートから実行します。

```bash
python -m pip install -r research/chatgpt_dt_r1/requirements.txt
python -m unittest discover -s research/chatgpt_dt_r1 -p 'test_*.py' -v
python -m research.chatgpt_dt_r1.cli --help
```

### 学習・校正・評価

DBは`sumidatadayoshi/keirin-data`のコミット`2a1260fb0940ad11160b56a36f9c24cc4fb2f6d2`由来です。

| ファイル | SHA-256 |
| --- | --- |
| keirin.db | 1bdad22b9744c9c5563f7bb1af31875170a3e6b7f4b0dd73fba8f98d645d8fc4 |
| keirin_2026q4.db | d915560877493816b90df8bcd5e7bdef45557f57100b4cd40a3d017cd959334d |

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m research.chatgpt_dt_r1.cli study \
  --archive /private/input/keirin.db \
  --archive /private/input/keirin_2026q4.db \
  --venues research/chatgpt_dt_r1/fixtures/venue_geometry.json \
  --allow-current-geometry-assumption \
  --output-dir /private/studies/new-run
```

`/private/...`は実際の私有ディレクトリへ置き換えます。出力はGit管理領域の外に新規作成し、原本を上書きしません。`--timings`で別途確認したタイム資料を追加できます。生DB、原本予測、校正のレースID列、鍵、ソース原文は公開しません。

### 予測・選択・画面

```bash
python -m research.chatgpt_dt_r1.cli forecast \
  --model research/chatgpt_dt_r1/evidence/20261128/frozen_model.json \
  --record /private/input/normalized-race.json \
  --history /private/input/admitted-earlier-history.json \
  --venues research/chatgpt_dt_r1/fixtures/venue_geometry.json \
  --at ACTUAL_AUTHENTICATED_ISO8601_CLOCK \
  --output /private/originals/forecast.json

python -m research.chatgpt_dt_r1.cli select \
  --forecast /private/originals/forecast.json \
  --odds /private/input/complete-precutoff-odds.json \
  --at ACTUAL_AUTHENTICATED_ISO8601_CLOCK \
  --output /private/originals/selection.json

python -m research.chatgpt_dt_r1.cli report \
  --report /private/studies/new-run/aggregate_report.json \
  --output /private/reports/aggregate.html
```

過去予測では`--at`を渡しません。外部資料を使う研究時計は`--analysis-at`へ渡します。CLI成功だけでは独立したソース認証になりません。`--calibrator`で実際の同ポリシー用の凍結校正を選択処理へ接続できます。

`report --owner-forecasts ...`は明示的な私有画面です。公開用画面は集計項目だけを許可し、別キーに添えた原本・氏名・鍵を取り込みません。HTMLは外部通信なしで開けます。実ブラウザ確認の状態は検証結果に記載します。

### 6局面・映像

```bash
python -m research.chatgpt_dt_r1.cli fit-phases \
  --history /private/input/history.json \
  --observations /private/input/reviewed-phases.json \
  --before YYYY-MM-DD --available-by ACTUAL_TRAINING_CLOCK \
  --output /private/models/phase-bundle.json

python -m research.chatgpt_dt_r1.vision process \
  --manifest /private/video/frames-manifest.json \
  --config /private/video/detector-config.json \
  --output /private/video/anonymous-tracks.json
```

`forecast --phase-bundle ...`で局面モデルを利用できます。最低学習件数は品質保証ではありません。局面の実映像評価・校正は別途必要です。

### 3モデル比較

```bash
python -m research.chatgpt_dt_r1.cli compare \
  --forecasts /private/exports/integrated.json \
  --forecasts /private/exports/codex.json \
  --forecasts /private/exports/chatgpt.json \
  --outcomes /private/results/admitted.json \
  --registry /private/registry/all-targets.json \
  --model-id existing-integrated --model-id codex-new --model-id chatgpt-dt-r1 \
  --output /private/reports/three-way.json
```

全対象と共通対象を分け、未出力を全対象側の失敗に計上します。固定点数Hit@1/2/4/9/12、二車単1/2、Log Loss、Brier、校正、カバー率を比較します。日単位ブートストラップで同一レースの差を評価します。未受領の競合出力を代用品で埋めません。

統合モデルは名前だけで同定しません。A/B各50%のモデルを対戦させる場合は、その実出力とSHA・重みmanifestが必要です。既存`official-and-research-ensemble-v1`の既定構成はA=.25、B=.25、research=.50で、これを勝手にA/B各50%の出場モデルと呼び替えません。独立CodexモデルはDT-R1の学習へ流用しません。

### 台帳・暗号化・再学習

`ResearchLedger`は3参加者のmodel/policy/schemaを固定し、原本と結果改訂を追記します。独立読戻しに失敗しても原本を保持します。元の選択がオッズ不足でHOLDでも、後の価格で同じ原本を書き換えません。復元先・暗号化shard・外部manifest SHA・履歴チェーンを検証し、状態欠落を新規初期化でごまかしません。

```bash
python -m research.chatgpt_dt_r1.cli ledger-init \
  --path /private/state/dt-r1.sqlite \
  --participant-id existing-integrated --participant-id codex-new --participant-id chatgpt-dt-r1

python -m research.chatgpt_dt_r1.cli ledger-status --path /private/state/dt-r1.sqlite

python -m research.chatgpt_dt_r1.cli ledger-checkpoint \
  --path /private/state/dt-r1.sqlite \
  --owner-public-key /private/keys/existing-owner-public.pem \
  --output-dir /private/checkpoints/new-snapshot

python -m research.chatgpt_dt_r1.cli ledger-restore \
  --checkpoint-dir /private/checkpoints/new-snapshot \
  --manifest-sha256 EXTERNALLY_PINNED_MANIFEST_SHA256 \
  --path /private/state/newly-restored.sqlite

python -m research.chatgpt_dt_r1.cli schedule-candidate \
  --path /private/state/dt-r1.sqlite --id next-candidate --due-at FUTURE_DUE_CLOCK
```

復元には既存の`RACE_AI_KEIRIN_PRIVATE_RSA_PEM`を使用します。新しい鍵・サービス・権限を作りません。`run-candidates`は既存スケジューラーから呼ぶ入口で、二重cronは追加しません。期限に達した候補を新しい私有先で学習し、失敗も記録します。Log Lossなら候補−基準の区間が負というように、指標の改善方向を固定します。

本番接続は既存の独立認証callbackと`OfficialAdmissionAdapter`へ接続します。callbackの`True`だけでは認定せず、元証拠・入力・保存原本を束縛したreceiptが必要です。`PinnedOfficialArchive`は固定コミットと既存の取得済み証拠を使い、資料を新たに取得したことにはしません。利用例と信頼境界は`admission.py`の冒頭を参照してください。

予定から正式出走表へ進むときは、新しく確認したarchive commitを固定したadapterを使います。既存の結果replayは原本との結合を必須とするため、予定しかなく公式原本がないケースの結果は、このfacadeではHOLDになります。そのケースを採点するには、対応する既存の独立した公式結果検証経路が必要です。

## 残る実証条件

- 対戦相手2モデルの凍結出力と同定manifest。
- 未見の未来レースに対する同条件の保存原本、独立読戻し、正式結果。
- 実選手の上がり・区間・局面の追加独立観測と、映像検出誤差の評価。既存アーカイブの上がりは学習済み。
- 同時点の完全オッズと検証済み払戻。今回の過去研究では可変点数の回収率は未測定。
- 既存GitHub経路での正式運用接続・継続保存と、保護されたレビュー。本番のモデル変更は研究ブランチの実装だけでは完了しません。

2026-11-28のタイム方針変更前の凍結モデルは、最終1周の全19列の係数が0で、上がりの基本6列は非ゼロでした。既存の実測結果は変更しません。変更後のCI・再評価・未来レース比較は別の実証とします。

旧`keirin_chat_dt_r1.py`、`run_dt_r1.py`はv0再現用に残します。今回の実行入口は`python -m research.chatgpt_dt_r1.cli`です。

## 出典

- [固定データ](https://github.com/sumidatadayoshi/keirin-data/tree/2a1260fb0940ad11160b56a36f9c24cc4fb2f6d2)。保存データの確認に使用し、公式の独立認証とは区別。
- [KEIRIN.JP 競走に関する質問](https://keirin.jp/pc/dfw/portal/guest/guide/question/race.html)。上がり半周の定義。
- [KEIRIN.JP 会場ガイド](https://www.keirin.jp/pc/jyoguide)。fixtureは会場別URL・取得時刻・原文SHAを保持。
- [Probability calibration](https://scikit-learn.org/stable/modules/calibration.html)。学習と校正評価を分ける考え方。校正の実装は本ディレクトリの独自実装。
- 研究契約は`docs/superpowers/plans/2026-11-28-dt-r1-pipeline.md`、所有者の詳細仕様・継続指示・AGENTS.mdに従う。
