# 競輪全国A/B自動予想の実装と本番引継ぎ（2026-11-18）

## 最上位指示
全国の全開催・全レースで予想の生成も無人化。共通4モデルPR71は未完成のためA/Bの必須要件から除外。Aは公開予想印や実際の競走情報を使った基準予想、Bは初周→打鐘→最終ホーム→最終バック→4角→ゴールの6局面と複数戦術の予想。Cは独立認証済みの過去連係履歴があるときのみ追加。Cが未完でもA/Bを止めない。

対象は2026-11-18の8会場79Rを不変Git登録済み。翌日以降は実開催一覧を読みレース数が変わる動的コホートを採用。ガールズ・6車・7車・9車・ミッドナイトも外さない。未生成は NO_FORECAST、未結果は HOLD として母数から削らない。

## 新たに実装した実計算と実行処理
- race_ai/keirin_nationwide_auto_generator.py：実出走前ソース（レースID、公開印、競走得点、観測された近況、H/B、脚質、実ライン予想、発走前日時/ソースSHA、根拠ありの勝ち上がり条件）を受け、Aの最大12点と、Bの複数の6局面シナリオから最大12点を自動作成。観測なしの情報、未確認勝ち上がり条件、実際の選手位置は捏造しない。現時点の重みは未校正の研究スコアで、的中確率ではない。
- scripts/keirin_nationwide_auto_forecast.py：全国当日コホート全race_idを一度走査。所有者の非公開正規化カードと元HTMLバイトSHAが存在し、公開締切候補に65秒以上の余裕があるレースのみ生成。欠測・時刻超過・別レース・重複を別HOLD理由に分類。予想とsourceデータを平文公開しない。
- race_ai/keirin_nationwide_auto_storage.py：既存所有者RSA3072公開鍵の指紋を固定、A/Bに別のAES-256-GCM鍵・nonceを生成しRSA-OAEP-SHA256で鍵をラップ。0700非公開フォルダに0600ファイルをcreate-onceで保存、同一ジョブでバイトSHA読戻し。原本の後書き禁止。
- scripts/keirin_nationwide_independent_cipher_readback.py：別GitHub runnerが暗号文のバイトSHAとA/B役割SHAを検証。秘密鍵によるRSA復号や公式結果の真正証明とは別。
- .github/workflows/keirin-nationwide-ab-auto.yml：10分間隔のschedule、ownerの非公開ソースの取り込み、A/Bの生成、暗号artifact保存、別runner暗号文読戻しを実装。実運用はmainへ統合後、本人がRepository Variableで明示的に有効化した場合のみ。PRではsource-free CIだけ動作。本番生成ジョブはSKIPPED。

## 本番投入に必要な非公開ソース
実行者は既に正当に利用可能な出走前データを次のように非公開のS3互換保管先へ置く必要がある。

S3_PREFIX/YYYY-MM-DD/cards/<race_id>.json
S3_PREFIX/YYYY-MM-DD/raw/<original_html_sha256>.html
S3_PREFIX/YYYY-MM-DD/registry/YYYY-MM-DD.json （2026-11-18以外）

カードJSONは RACE_AI_KEIRIN_NATIONWIDE_PRE_RACE_FACTS_V1 の厳格なスキーマとし、MARKS・RACECARD・LINEのソースURL/HTML SHA/取得時刻、選手別の登録ID/車番/公開印（不明なら明示的UNMARKED）/競走得点/近況スコア（原本に値がある場合のみ）/H/B/脚質、実際に確認したライン及び公開締切予定を持つ。ガールズは固定ラインを作らない。大会勝ち上がり条件が独立に確認できない場合はUNKNOWN。

設定名：RACE_AI_KEIRIN_AB_AUTOGEN_ENABLED=true（Repository Variable、明示的owner opt-in）、RACE_AI_AB_SOURCE_S3_PREFIX、RACE_AI_AB_SOURCE_REGION、RACE_AI_AB_SOURCE_ENDPOINT、RACE_AI_AB_RSA_PUBLIC_PEM_B64（Variables）。既存本人保有ソースに認証が必要な場合、Secrets RACE_AI_AB_SOURCE_ACCESS_KEY_ID、RACE_AI_AB_SOURCE_SECRET_ACCESS_KEY を使う。これらをこのチャットやPublic Gitに貼り付けない。新規課金先や秘密情報は今回設定していない。

注意：原本HTMLのSHAを照合しても、提供元の権利・主催者の正式締切時刻・取得時刻の独立認証は自動で完成しない。既存WINTICKETのmain取得は初回1GETで拒否扱いになった実績があり、今回それを回避していない。既存のWINTICKET部分出走表だけでは、公開印・ライン・近況等が揃うとは限らない。今ある真のソースをこの新スキーマへ変換する実データアダプターが未接続。

## 合格状況：合成と本番を混ぜない
- 実レース全国登録：2026-11-18は8会場79Rが事前登録済み。全件を正しく扱う研究テストは既存CIで成功。
- 手動研究A/Bの締切前AES保存の既存実レース証拠：西武園1R 1件（commit 5b4abe91）。今回の新自動生成コードで全国全件を予想したわけではない。
- 自動生成エンジン：GitHub Actions source-free run 44198324623、架空レース原本＋実RSA/AES暗号処理の30件 PASS。
- 既存PR研究テスト群：run 44198324541、232件 PASS。mainのみの本番ジョブはSKIPPED。
- 当日実レースの新自動A/B生成・暗号保存：0件確認。全国公式結果を使った実A/B完走：0件確認。C認証済み追走ラベル：0件。

## 未完成と今後の実作業
1. 実在の合法的な提供元の出走前データとソース時刻を、全国全開催にわたって継続収集し、カードスキーマへ自動変換。既存ソースアクセス拒否は無理な再試行・隠しAPIで回避しない。
2. 本人管理の非公開永続保存を既存インフラと接続し、main統合と本人のオプトイン後、未来の実レースで自動起動→生成→AES保存→別runner SHAを一巡させる。
3. 同じrace_idについて複数runが重複生成しない「跨ぎrun create-only 永続受付台帳」が必要。現在の0700ローカルファイルの存在チェックだけではrunnerをまたぐ重複を防げない。21日のArtifacts保持を完全な永続正本と扱わない。
4. 公式締切変更・返還・中止・同着・公開結果訂正を確認し、A/Bの同じ母数でHit@1/全候補/仮想ROI/HOLD率を採点する。結果から予想を再生成して遡及合格させない。

**正式完成は未達。** 自動予想エンジンとGitHubの安全な処理土台は実装済みだが、本物の全国データ供給と本番起動・永続復旧・結果自動採点は未接続。PR #291はDraft、main・Secrets・追加課金・自動購入は変更していない。
