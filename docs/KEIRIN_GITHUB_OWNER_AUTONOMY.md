# RACE-AI 競輪部門：GitHub Actions単独自動化

## 変更しない条件

RACE-AIはPublicを維持し、個人PC、Windows/ZBook/MacBook、自前self-hosted runnerを一切必須にしない。ChatGPTタスクは起動係にしない。GitHub-hosted Ubuntuで定期実行する。

既存PR71の4モデルを使用し、モデル係数・予想原本・結果照合方式を勝手に変更しない。

## 自動運転の経路

1. GitHub Actionsが毎時UTC11分と41分に起動（実際の発火遅延・欠落はあり得る）。
2. 公開読み取り専用ジョブで、出走者、347項目の確認状況、まだ足りない必須データを確認。公開ログには個人の入力値・予想買い目・オッズの元データを出さない。
3. GitHub-hosted Ubuntuの本番ジョブが、既存のGitHub保管ブランチ state/keirin-encrypted-history を読み込む。新しい世代専用保存先は state/keirin/pr71-production/v1。旧来の state/keirin/v1（合成テスト専用）とは厳密に区別する。
4. 既存Node AES-256-GCMの scripts/keirin_github_checkpoint.mjs と、既存SQLite整合性バックアップの scripts/keirin_github_sqlite_snapshot.py を再利用。GitHub Actions Secretsから本番鍵を受け取る。平文・鍵はPublic Git履歴へ出さない。
5. 提供元の権限を確認した完全な未来レース入力が存在するときに限り、既存の licensed JSON export、stage_permissioned_deliveries、stage_existing_owner_pre_races、FourModelRankLedger を使って4モデルの予想を締切前に生成・保存。欠損値を捏造しない。結果が実際に存在するレースだけ既存PDCAを再計算。
6. 本番予想または既存結果改訂に変更がある場合のみ、暗号化SQLiteを新しい世代番号でcreate-once保存。前の暗号文SHAに鎖付けし、Gitにforce pushしない。
7. 別のGitHub-hosted Ubuntuジョブで暗号文を再取得・復号・SHA一致・SQLite完全性と4モデル予想原本を検証。これが通るまで「自動保存完了」とは認めない。

## 利用するGitHub Secrets

保存鍵 RACE_AI_STATE_KEY は既存Nodeコード仕様の32バイト秘密鍵（base64形式）。現在の値や存在確認をチャットへ貼り付ける必要はない。

実データの供給に認可済みのAPIがある場合だけ、次の項目をGitHub Secretsで設定する。提供元のURL・契約・機械利用権限が不明なら設定しない。

- RACE_AI_KEIRIN_FEED_ENDPOINT : 許可された公開HTTPS JSONエクスポートURL
- RACE_AI_KEIRIN_FEED_RIGHTS_REF : 対応する使用権利識別子
- RACE_AI_KEIRIN_LICENSE_MANIFEST_B64 : 本物の承認台帳JSONをbase64化した内容
- RACE_AI_KEIRIN_LICENSE_DOCUMENT_B64 : 実際の承認文書をbase64化した内容（台帳のSHA一致が必要）
- RACE_AI_KEIRIN_FEED_TOKEN : 提供元が正規に発行した任意のBearerトークン

ここで使うのは実際の提供元が認めた経路のみ。公開ページを取得できることだけで機械利用権限が独立に証明されたとは扱わない。ライセンスがなければ機械入力をHOLDし、前回の暗号化された予想原本が存在する場合にのみ復元照合を続ける。

## 暗号公開の注意点

公開GitHub上では暗号文の存在、大きさ、更新時刻、ハッシュが見える。本番鍵が後日流出すれば、過去の暗号文が復号される可能性がある。所有者が2026-11-09に承認したAES暗号文のみの公開範囲を維持し、予想原本や個別選手データの平文は公開しない。GitHubが恒久的なバックアップを保証するわけではない。

## 本当の合格条件

- GitHub schedule起動の実run IDと時刻。
- 許諾と前後関係を確認した本物の未来レース選手入力。347項目の検査と既存4モデルの必須入力が成立すること。
- 元の4モデルによる全210/504組の締切前予想を原本として保存すること。
- GitHubの暗号化Git履歴への保存と、別runnerでの独立復号・SQLite整合性・予想原本SHA一致。
- 公式結果が入ったレースに限って既存PDCAを更新。Top8、万車券捕捉率、点数、仮想収支を分けて検証。

現状、実レースの4モデル全件が揃った締切前予想・暗号保存・次回独立読戻しの本番実証は未達。実データ不足は並行して解消する別課題。合成テスト合格を本番成績と呼ばない。

## PC方式の廃止

前回追加したWindows self-hosted runner、Private化強制、端末固有DBパスをGitHub Secretsに保存する方式は採用しない。旧Windowsセットアップスクリプトとそのテストも削除し、ここに記載したGitHub-hosted運用へ一本化する。
