# 競輪予想の GitHub Actions 単独自動化

## 結論

ChatGPTのタスクは使わない。GitHubの `.github/workflows/keirin-pr71-owner-autonomous.yml` がスケジュールを担当する。既存の競輪映像収集・夜間研究ワークフローはそのまま残す。ワークフロー内で予想アルゴリズムは新設せず、固定された PR #103 の既存 PR71 4モデル・347項目検査・SQLite読戻し・PDCA処理を使用する。

- `schedule` はUTCの毎時11分・41分（おおむね30分間隔）でGitHubが起動。GitHubのscheduleイベントには遅延や欠落があり、レース終了の瞬間や締切直前の実行保証ではない。
- `public-preflight` はGitHubホスト型で、WINTICKETの公開当日インデックスから出典に裏付けられた「次の未締切7/9選手レース」1件を検証。公開ログへは件数・SHA・不足数・HOLD状態だけ。モデル実行や永続保存をしたとは主張しない。
- `private-owner-PR71` は **ユーザーが明示的に有効化したときだけ** 実行。デフォルトはスキップ。信頼する自分のWindows self-hosted runner上の既存非公開DBとinboxを使用。ChatGPT経由の起動は不要。
- `synthetic-ci` はワークフロー修正時に必須の回帰テスト。成功しても実予想ができた証拠にはならない。

## 非公開ランナー接続方法

1. RACE-AIリポジトリにWindows x64の信頼できるself-hosted runnerを登録し、専用ラベル `keirin-owner-private` を割り当てる。GORIQなど別用途の汎用runnerへ誤配信しない。ランナーは自分が管理する端末のみにする。
2. 端末内の既存の非公開SQLite（新規で空の本番DBを作らない）、先に確保したinbox、権利を確認した提供資料を準備する。SQLiteは永続ストレージに置く。ランナーが停止中ならGitHub Actionsのprivate jobは実行待ちになり得る。
3. Repository Secretsに次の**絶対パス**を設定。値をActionsログや公開コミットへ書かない。
   - `RACE_AI_KEIRIN_OWNER_DB` : 既存の `.sqlite3` / `.db` ファイル
   - `RACE_AI_KEIRIN_OWNER_INBOX` : 非公開の既存inboxディレクトリ
   - `RACE_AI_KEIRIN_OWNER_GRANT_MANIFEST` : 任意。機械取得・推論・非公開保存を承認済みのライセンス台帳JSON
4. Repository Variables `RACE_AI_KEIRIN_OWNER_RUNTIME_ENABLED=true` を設定すると、**mainのschedule/手動起動だけ**でprivate jobが稼働。接続準備前は設定しない。
5. 公開ページのオーナー承認済み個人研究用取得も端末に保存したい場合のみ、`RACE_AI_KEIRIN_OWNER_PUBLIC_FETCH_ENABLED=true` とする。通常公開ページの取得が提供元によって許されるかは本人の運用責任で確認し、403/429で停止。内部API探索やアクセス制限回避はしない。

`OWNER_GRANT_MANIFEST` が指定された場合、コードは権利資料のSHAと有効期限を検証し、従来の `stage_permissioned_deliveries` と `stage_existing_owner_pre_races` を使用。指定しない場合は個人の**研究専用**ルートであり、利用許可の独立証明にはならない。

## 運転時の処理

1. GitHub cron起動。公開プレビューでは、出走・締切時刻・候補数と元ソースSHAだけを記録。
2. private jobでDB・inboxを検証。欠けていれば `HOLD`。プライベートの原本は公開Actions artifactに載せない。
3. 任意の個人用SS​​Rフィーダーは、元出走表をオッズが未公開でも保存する。オッズ取得後も当時の出走表・取得時刻・SHAを変更しない。最大16レースは**1回の取込保護量**であり、その日の全レース採点上限ではない。
4. 347項目の検査と既存4モデル必須数値の検査。元データが足りなければ予想生成を止める。空欄を0や平均値で補ったり、結果を見てから予想を作らない。
5. 入力と時刻・権利条件が揃っている場合、既存4モデルを同じ未来レースへ適用して、元出走情報と順位予想を既存非公開SQLiteへ凍結、読戻し検証。通常の結果到着後には**既存PDCA**が記録の改訂を再照合する。オッズは予測特徴量に混ぜない。
6. ランナーを止める／変数をfalseへ戻すと次回の非公開実行を止められる。GitHub Actionsによる外部プロバイダーAPIライセンスや正しい予想精度は自動的には保証されない。

## 現在の未完了条件

2026年11月9日の松戸8Rでは、実際の出走者7人と3連単210通りが取得できたが、既存モデルの必須入力93枠中81枠が不足。11月10日青森3Rでも必須93枠中79枠不足。**本物の4モデル未来予想は0件**。したがって、このGitHub Actionsの実行配線が成功しても、実予想成功とは別に判定する。

また、`private-owner-PR71`は信頼できるランナー、非公開DB、原本供給が未確認の間は無効。この構成はGitHubの自動起動を優先し、モデルのデータ充足・利用許諾・永続保存の3条件を満たしたものだけ予想成功と呼ぶ。新しいChatGPTタスクは一切作成しない。

## 検証

- 元モデル：`race_ai/keirin_pr71_four_model_rank.py`、`race_ai/four_sport_model_suite.py`
- 既存本番パイプライン：`scripts/keirin_permissioned_owner_agent.py`、`race_ai/keirin_owner_sqlite.py`
- 出走表/オッズ：`scripts/keirin_github_owner_future_intake.py`、`race_ai/keirin_owner_captured_ssr_intake.py`
- Actions用コード参照：PR #103の固定SHA `60b739bfb9861cbc48864b83651cfc2fb89c0fe7`。自動的に未審査の最新HEADを追わない。
- CI：固定SHAで既存入力・予想・保存の合成テスト。モデル係数は変更しない。

## 注意

公開リポジトリに秘密鍵・選手個別データ・出走表HTML・オッズ原本・非公開DBをコミットしない。見えるのは公開情報に基づく状態、欠損項目数、CI結果のみ。公開GitHub Actionsのログにディレクトリパス等が表示されないようにする。自分のWindows private runnerは高信頼な専用ラベルで保護し、PRから秘密情報を実行しない。
