# 全レース・既存全モデルの実行と不足検出

既存Draft PR71の追補。16系統を新しいモデルに置き換えず、既存関数へ接続する。**この実装の合成試験成功は、実開催全件の予想成功ではない。**

## 実行層

`race_ai.existing_model_dispatch.dispatch(schedule, native_inputs, *, now, allow_source=None, originals=())`

- scheduleは実際の `race_id / sport / cutoff_at / stage` の配列。必要なら各行に `model_versions={model_id: version}` を指定する。件数だけからレースIDを捏造しない。
- native_inputsは `{race_id: {stage: {入力グループ: ネイティブ入力}}}`。入力グループは `boat_ab`, `boat_clite`, `boat_tactical`, `boat_full`, `boat_observed`, `shared`, `autorace_personal`, `boat_pdca`, `seller`。`shared`へ真正なlearned_modelが渡された場合は既存の学習済み系統も別に実行する。
- 共通スナップショットを別モデルのために架空特徴へ変換しない。各モデルの既存スキーマと公開/観測/締切時刻・選手ID・利用許諾を満たすネイティブ入力が必要。
- A/B、総合ボート2種、観測相性2種、共通4種のようなグループ出力を先頭1件だけで捨てず、それぞれ別の元出力/SHAとして保持する。27契約テストで16系統の既存計算関数を実際に実行した。
- PDCAは既存 `buildChallenger` をNodeで純粋計算する。`scripts/existing_pdca_offline.mjs` は最大2MiBのstdinのみ、現在事実と24件以上の過去同会場結果を検査する。D1/Worker/外部DB/HTTP/デプロイ/モデル昇格は呼ばない。
- originalsは元のdispatch slotを渡す。race/stage/model/version/native本文とSHA・親コンテキストを検査して保持。グループ全件が保存済みなら計算しない。兄弟モデルだけ不足する場合、既存グループ関数内部の計算は起こるが、既存原本を置換・更新しない。求めたv2を保存済みv1で満たした扱いにしない。
- 実入力は既定で許可しない。source_evidenceの対応だけでなく、信頼した呼出元の `allow_source` がanalysis用途を許可する必要がある。任意の自己申告trueやsyntheticタグで実スナップショットの許可を回避できない。

生成結果は `GENERATED_UNATTESTED`。元保存の再利用、入力不足、真正学習物不足、期限超過、モデル条件での選外、未認可、入力不整合、対象競技外を別slotとして残す。ここではサーバーreceiptを発行/認証せず、正式予想・公式Hit@8に昇格しない。返されたpredictionとretained_originalsは**私有データ**。public Git/ログ/無暗号の公開artifactに送らない。

Sellerの07:00以前・条件該当・1日最大5件という既存のモデル定義も保存する。分割入力や再実行で上限を迂回しない。選外はRULE_FILTEREDで、全レース予想済みには数えない。全件生成を実現するために元ルールを変えたふりや、締切後の再生成は行わない。

## 全対象の不足行列

`race_ai.existing_model_coverage.coverage_matrix(schedule, forecast_rows, *, stages=None, now=None, model_versions=None)`

実際に渡された全レース×登録16系統×明示された段階/版を展開する。ボート15、競輪5、オート6、競馬5が競技上の適用対象。異競技専用モデルを無理に走らせないが、対象外の行も表示する。P0/P1のほか、既存オートのA_PRE_TRIAL/B_POST_TRIALは元の意味を保つ。

予想済みの他モデルを理由に不足モデルを省かない。生成しただけの行は凍結数へ入れない。receiptの時刻/SHAの構造検査と独立認証を区別し、供給されたメタデータだけでall_models_operationalをtrueにしない。旧 `coverage(rows, sport_counts)` は互換の件数報告のままで、完全性の証明ではない。

以前の当日予定枠144/75/20/59を仮定すると、1段階の表示行は16×298=4,768、うち競技上の適用2,950/対象外1,818になる。ただしこれは既存記録の件数からの計算例。正式な当日全開催の完全性や全モデル事前保存の実証ではなく、段階数を無条件に2倍してはならない。

画面の研究ページはデータ0件でも全16系統を表示。全レースページも対象レース数と必須適用モデル数を表示し、実行できたモデルだけの一覧にしない。登録・取込原本数・段階/版・不足・正式実運転を区別する。

## 確認と残る接続

Python618件、Node165件成功。合成4競技入力で64モデルslot（適用31/対象外33）を作り、共通16予想を生成、入力不足11/学習物不足4を残した。実レースは0、原本上書き0、source GET0、receipt作成0。この出力から「16モデル全部の実開催予想が完成」とは言わない。

元の既存Actions巡回は5ボート基準＋学習版2系統のまま。全16の新実行層を、実入力・私有永続保存・独立freeze/result検証へ接続して実運転する工程は未完了。現在の入力/保存権限を増やさずに自動接続したと偽らない。取得240/240停止済みrunの即時再起動・上限増加・新workflow/task/scheduleなし。

私有原本の調査は [保存先調査](evidence/2026-11-04/all-existing-models/PRIVATE_SOURCE_DISCOVERY.md)、試験証拠は同ディレクトリのvalidation-summary.jsonとログを参照。既存PR72のSHA固定リーダーを同じPR71へ再利用したが、原本の実バイトがこの環境にないため、今回の実原本読戻しは0件。実機iPhone Safari、継続運転、未来精度向上の実証も別の未達条件。
