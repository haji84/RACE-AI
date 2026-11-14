# 会場別入力を使った個人研究用の実データ学習（2026-11-07）

所有者の個人研究として進める指示に基づき、締切前に保存・認証された会場別入力と公式正常確定結果が揃う**実8レース**で、既存2系統の係数推定を実行した。状態は `FITTED_SHADOW_ONLY`。**TRAIN 6レース、検証用holdout 2レース**で、各系統の8係数中6係数が更新された。基準係数と本番モデルは変更していない。

11月6日の `HOLD_MODEL_TRAINING_PERMISSION` は、その時点の用途未確認による保留履歴である。今回は所有者の個人研究という利用判断を別の認証済み記録として受け付け、実学習を進めた。提供元の許諾を取得したという意味には変更していない。この研究実行のために追加の許諾確認を求める工程は残していない。

## 実行結果と対象

公開可能な件数記録は [venue-personal-research-counts.json](evidence/2026-11-07/venue-personal-research-counts.json)。特徴量・学習係数・予想原本・結果原本の平文は含めていない。

| 項目 | 実測結果 |
| --- | --- |
| 保存済み原本から選んだ異なるレース | 14 |
| 会場別入力を原本に含む学習対象 | 8。既存の最低8件条件を維持 |
| 除外したレース | 6。会場別特徴量を後から補わない |
| TRAIN / holdout | 6 / 2。結果の利用可能時刻順に分割し、holdout結果は係数推定に使わない |
| 入力段階 | 全8件が **P0（program-only、展示入力なし）**。会場別履歴と番組表等を使用し、実展示を観測したP1ではない |
| 学習した既存系統 | `boat-observed-pairwise-factor-v1`、`boat-observed-pairwise-start-v1` |
| 更新係数 | 各系統6個。新しいモデル系統は作成していない |
| 展示2特徴量 | `exhibition_start_seconds`、`exhibition_time_seconds` はTRAIN支持数0で、両系統とも基準係数を維持 |
| その他のTRAIN支持数 | `recent_mean_finish` は5。`course_mean_finish`、`course_mean_st`、`motor_top2_rate`、`national_win_rate`、`recent_mean_st` は各6 |
| 所有者研究判断で対象に含めた取得元 | 62 |
| 提供元レビュー未確認の取得元 | **62のまま**。`provider_permission_confirmed=false`、`provider_review_missing_sources=62`、`unapproved_training_sources=62` を維持 |
| 学習の根拠 | `training_basis=OWNER_PERSONAL_RESEARCH`。提供元の用途別許諾と所有者の研究判断を区別 |
| 基準係数・本番・購入 | 基準係数変更なし、本番昇格なし、実購入なし |

同じ保存済み入力と結果をCLIで再実行し、推定係数と評価指標の一致を確認した。これは再現性の確認であり、実際の未来レースで学習済み候補を比較した結果ではない。

## 暗号化した候補の保持と復元

最初の実学習候補を指す公開ポインターは [audit/state/boat-venue-learning-input.json](../audit/state/boat-venue-learning-input.json)。既存の `state/boat-pdca-transfer` refに追記し、以前の暗号化履歴と無関係の状態ファイルを保持した。新しい保存サービスや状態refは追加していない。

| 識別子 | 値 |
| --- | --- |
| 学習内容SHA-256 | `513e986fede6f9f66ad7579d6b9c646ad83a933984d4fe3948d97ba1a7f9fc9c` |
| 保存元コミット | `138fde975a18fc5a760cc6b119c3eb1b589e99e2` |
| 認証付きmanifest SHA-256 | `e5d52423ccd3b1b461c0f1524eb44db4495a4c83d9bda764b22af1fa0f77e0f8` |
| 会場別データセットSHA-256 | `3deb20e26ccc73add405032a45a790abb02d8424e43bb7d1e9b45861ab3d7a19` |
| 所有者研究判断SHA-256 | `23d5655f75812a5b2778eda52cc79851dcf5e544aca55c0162a16813088e7586` |

保存する候補は `learning.enc`、認証付き `learning.json`、件数のみの `summary.json` の3ファイル。GitHub上の固定コミットから取得した暗号文を実際の所有者キーで復号し、manifest認証・暗号文SHA・学習内容SHA・公開件数の一致を確認した。`encrypted_readback_verified=true`、`plaintext_published=false`。既存候補を上書きせず、同じ版の再発行で異なるバイト列を受け付けない。

この保持・復元は、未来の予想に必要な独立した締切前保存証拠の代用にはならない。保存ポインターに架空のartifact IDや予想時刻を付けていない。

## 利用条件の確認記録

2026-11-07 00:35 JST頃（11月6日15:35 UTC）に次の公開4ページだけをGETし、すべてHTTP 200を確認した。転送追従なし。**この段階の新規提供元データ取得は0件、艇愛DBデータAPI取得は0件**。4件の利用条件ページ取得と、データ取得0件を区別する。問い合わせ・フォーム送信も行っていない。

| 公開資料 | 確認した原文・内容 | 取得HTMLのSHA-256 |
| --- | --- | --- |
| https://boatrace-db.jp/about/data/ | 「認証やAPIキーは不要です。個人利用・研究用途はご自由にどうぞ。」 | `1a04f24ad11e21e378d1753cda45fd524b21abbc53a433e1206ad0cbdd5031bc` |
| https://boatrace-db.jp/about/rules/ | 「当サイトで集計した数値 (勝率・コース別成績など) は、出典として当サイト名とURLを示していただければ、記事やSNS、個人の研究などに利用して構いません。」 | `e6455accfb3dcca3d3c52853915922a4e3245abfb71cb4c2fe08120bca6e8238` |
| https://www.boatrace.jp/owpc/pc/extra/data/download.html | 「全国24ボートレース場で開催されたレース成績をダウンロードすることができます。」 | `8b232fa8f904446d276ee04a1963f56a9ad36486c41053b525be7e16d290348c` |
| https://www.boatrace.jp/owpc/pc/extra/policy.html | 「私的使用など法律によって認められる範囲を超えて、無断で使用（複製、改ざん、頒布などを含む。）することはできません。」また「その他いかなる権利も許諾するものではありません。」 | `e160e8c2d1b4dbe16da01326dee77b21da73990ca3543afdc27910c9803c45e8` |

確認した4ページでは、個人・研究用途の記述があり、AI・モデル学習の明示的な禁止は見当たらなかった。公式サイトの包括的な学習許諾を確認したとは扱わず、個人利用なら常に許諾が不要という一般的な法的結論も記録しない。所有者研究判断の認証は、提供元の権利付与を証明するものではない。

出典はBOAT RACEオフィシャルウェブサイトおよび艇愛ボートレースDB（https://boatrace-db.jp/）。艇愛の条件には、表示時の出典・リンク、日次数回までの取得と保存利用、API内容をそのまま第三者へ再配布しないことが含まれる。短時間の大量ページ取得や、公式サイトの運営を妨げる大量アクセスも制限されている。これらの条件と主催者発表との照合を維持する。

## 既存学習器・暗号化推論への接続

`boat_venue_learning.training_intake` が凍結済みの最新入力だけを選び、既存 `observed_weight_learning.fit_from_verified` が従来の最低件数・時系列分割・同じ式で学習する。取得元レビューの `PermissionPolicy` 自体は変更していない。所有者の判断記録は、原本ポインター全体・認証済み内容SHA・データセットポインター全体・取得元とrights refの完全な集合に専用ドメインのMACで結び付ける。対象を変更した記録や改変記録は最適化前に拒否する。既定90日の期限は運用記録の見直し期限であり、提供元が設定した利用許諾期限ではない。対象が増えた場合は、この継続指示の範囲で明示的な記録作成CLIを再実行する。学習器やActionsが署名を自動発行する構成にはしていない。

```bash
python -m scripts.boat_venue_learning \
  --restored-dir /private/verified-production-readback \
  --owner-research-record audit/state/boat-venue-learning-owner-research.json \
  --out-dir /private/new-venue-learning
python -m scripts.boat_venue_learning_handoff readback \
  --input audit/state/boat-venue-learning-input.json \
  --out-dir /private/retained-learning
```

所有者キーは既存の環境変数から読み、コマンド引数やログへ渡さない。`boat_venue_learning_context.context_from_encrypted_artifact` は実artifact IDのGitHubメタデータ、ZIPのSHA・大きさ・保存時刻・期限・リポジトリと所有者暗号化を確認し、既存 `make_shadows` の入力契約へ学習内容を渡す。`make_encrypted_shadows` は同じ基準入力から研究用予想を作り、暗号化して保存する。独立した締切前保存証拠を自動的に付与せず、平文の旧 `national.json` 経路へも渡さない。この推論接続・暗号化P1の保存受入・結果後PDCAは合成入力で検証した段階であり、実際の未来P1出力とは別である。

既存の `.github/workflows/forecast-audit-ui.yml` の原本復元ジョブで同じ学習CLIを実行し、独立した全選手データ復元ジョブで保持済み候補を読み戻す。新しいジョブ、定期実行、権限、外部保存先は追加していない。

## 直前予想・結果後PDCAへの追加接続

通常予想の独立保存を終えた後に `venue-research-forecast` を呼び、既存学習済み候補の実artifactと会場別gridを**研究用P1の新しい予想基準時刻を固定する前**に復元する接続を追加した。通常予想の締切前保存は研究処理を待たない。最初のCIで生成された実artifact `13521002313`、学習SHA `ba7ee462edf570128b8d46055332e68bef721788de90de03b00d6501bf99b2c2` を [context input](../audit/state/boat-venue-learning-context-input.json) に固定している。この実ZIPを所有者キーで復元し、実際のGitHubメタデータ・SHA・サイズ・元HEADと照合し、最初のローカル学習と係数・指標が一致した。候補のGit保持元は `dcc9905239f4f070c00b9e6ad5d665ac91c724ac`、manifest SHA `3b4a4ac9204322cdfe5119f4c5ed78f6a5d36418c9babbc1cede2139cde03442`。最初の候補SHA `513e...` とこのCI生成版を同じ保存証拠へ付け替えていない。

実際の候補ZIPを再利用し、実メタデータを再取得した通常のruntime preloaderでも、全63,432プロフィールの所有者キー復元と学習内容の読み込みを確認した（2026-11-06 16:46:57 UTC）。これは実P1予想の生成ではない。

通常の原本は2取得元、過去結果を含む場合は3取得元の契約を維持する。暗号化研究経路だけで原本をコピーし、実際の生成時刻を新しい予想基準時刻として会場別履歴を結合する。変更後の同じ6人・同じ入力から基準2系統と学習2系統を再計算し、元の通常P1は変更しない。取得元は原本で検査したURL/rightsと固定gridの完全一致で個人研究の解析対象に含め、提供元の権利を付与したとは扱わない。

既存 `existing-model-round` 内で、この別予想を暗号文だけのartifactへ保存する。実GitHubの保存時刻を丸秒精度の上端まで考慮して締切前と確認できた場合のみ受け入れる。以後の巡回は、受入済みartifactの参照を既存continuity/resultへ保持して前のworkerから復元し、既存監査が既に確認した最新公式結果を既存 `score_shadows` へ渡す。未確定・返還・結果不一致は通常採点へ含めない。予想・結果原本・全比較内容は暗号化し、公開出力は件数とモデル別集計だけとする。

成功した予想だけをアップロード対象へ移し、遅延・部分保存は別の私的隔離先へ保持する。結果後PDCAはレース別の3ファイルへ分割し、既存codecの8MiB上限を変更せず、大きな原本ZIPを各レースのSQLiteへ重複埋め込みしない。予想とレース別PDCAの3ファイルは既存の暗号化publisherで同じGitHub state refへ追記し、固定commit・manifest・学習SHAのポインターを保存する。元artifact ZIPは暗号文と件数だけの形式を再認証してから、そのまま別の同一ref内のcontent-addressed namespaceへ保存し、メタデータ項目とowner MACも保持する。GitHubからのHTTP応答メタデータ原文のバイト一致を主張するものではない。Git認証は既存の `GH_TOKEN` によるプロセス内一時設定だけで、終了時に元の環境へ戻す。リポジトリ/全体の認証設定や権限を変更しない。独立保存失敗、期限切れ、復元失敗、入力不一致、保持失敗は研究経路のHOLDとして記録し、通常モデルの予想・結果処理を置換しない。

新しい定期タスク・workflow・モデル系統・保存サービスは追加していない。既存workflowへ所有者キーと既存の暗号化依存を渡す。1artifactの検査上限は当日24会場×12Rと64MiBであり、通常予想の対象数を3件に制限する変更は行わない。暗号化PDCAはレースごとに既存SQLite codecの8MiB上限を維持し、1レース自体が上限を超える場合はHOLDになる。大量の同時研究予想について実レースでのPDCA成功まで実証したとは扱わない。

候補の永続暗号文と、推論前に検証する7日期限の独立artifactは別の役割である。期限後も自動的に過去のreceiptを有効とせず、次の既存CIの候補を確認してcontext inputを明示更新する。本番モデルの自動採用は実装していない。

## 検証済み範囲と次の実測

並行変更を取り込んだ最終ローカル全体テストは **2,062件実行・失敗なし・112件skip**、初期学習接続の対象テストは **46件成功**。追加した私的P1・PDCA・復旧・既存接続の最終対象テストは **102件成功**。所有者判断の認証・期限・対象固定、holdout分離、暗号化候補の読み込みと保持、改変・誤キー・不正ポインターの拒否を検証した。**最初の実学習HEAD `b466fd8fad89b75999c3a22791af7396eadd045a` の [Actions 42251633906](https://github.com/haji84/RACE-AI/actions/runs/42251633906) はsuccess。以下の直前予想接続を追加した最終HEADのCIは記録時点でpending**。

学習済み候補を使った実際の未来P1予想、その予想の独立した締切前保存、公式結果との比較とPDCAはまだ行っていない。合成入力による `make_shadows` 接続テストを、実際の未来レースの実績として数えない。8件の実学習と2件の過去holdoutだけで、予想精度改善、会場別データ単独の効果、学習済み係数の優位性を証明したとは報告しない。

次の最小工程は、この実装を実際の未来P1入力が取得できる既存巡回で確認し、既存基準モデルと学習済み候補を同条件で出力し、候補の独立保存時刻が予想より前であることと、予想原本の保存が締切前であることを確認すること。その後に公式結果・改訂履歴・採点を追記する。本番昇格は今回の実行範囲に含まれない。
