# RACE-AI 競輪部門：GitHub Actions単独自動化

## 変更しない条件

RACE-AIはPublicを維持し、個人PC、Windows/ZBook/MacBook、自前self-hosted runnerを一切必須にしない。ChatGPTタスクは起動係にしない。GitHub-hosted Ubuntuで定期実行する。

既存PR71の4モデルを使用し、モデル係数・予想原本・結果照合方式を勝手に変更しない。

## 自動運転の経路

1. GitHub Actionsは現在UTC毎時03・08・13・18・23・28・33・38・43・48・53・58分に起動する設定。発火遅延・欠落はあり得るため、schedule設定だけで本番成功と数えない。実際の暗号保存時刻を別途確認する。
2. 公開読み取り専用ジョブで、出走者、347項目の確認状況、まだ足りない必須データを確認。公開ログには個人の入力値・予想買い目・オッズの元データを出さない。
3. GitHub-hosted Ubuntuの本番ジョブが、既存のGitHub保管ブランチ state/keirin-encrypted-history を読み込む。新しい世代専用保存先は state/keirin/pr71-production/v1。旧来の state/keirin/v1（合成テスト専用）とは厳密に区別する。
4. 既存Node AES-256-GCMの scripts/keirin_github_checkpoint.mjs と、既存SQLite整合性バックアップの scripts/keirin_github_sqlite_snapshot.py を再利用。GitHub Actions Secretsから本番鍵を受け取る。平文・鍵はPublic Git履歴へ出さない。
5. 提供元の権限を確認した完全な未来レース入力が存在するときに限り、既存の licensed JSON export、stage_permissioned_deliveries、stage_existing_owner_pre_races、FourModelRankLedger を使って4モデルの予想を締切前に生成・保存。欠損値を捏造しない。結果が実際に存在するレースだけ既存PDCAを再計算。
6. 本番予想または既存結果改訂に変更がある場合のみ、暗号化SQLiteを新しい世代番号でcreate-once保存。前の暗号文SHAに鎖付けし、Gitにforce pushしない。
7. 別のGitHub-hosted Ubuntuジョブで暗号文を再取得・復号・SHA一致・SQLite完全性と4モデル予想原本を検証。これが通るまで「自動保存完了」とは認めない。

## 2026-11-11 再確認：個人研究用公開ページ取得とAPIは別経路

- 2026-11-09に利用者が個人研究用のWINTICKET・KEIRIN.JP公開ページ自動取得を承認済み。GitHubに記録された正本は `scripts/keirin_cloud_owner_inputs.py` の `PROFILE = 'owner-approved-winticket-keirinjp-20261109'`。
- `scripts/keirin_cloud_pr71_state.py::_licensed_inputs()` はこの設定がある場合、`RACE_AI_KEIRIN_FEED_*` の別途API/JSON契約情報が**未設定でも**既存の個人用候補取得を呼び出す。これは2026-11-10の `docs/superpowers/plans/2026-11-10-cloud-owner-source-connection.md` と一致する。
- PR #130の `keirin_live_source_readiness.py` が4件の**API専用設定を全経路の必須条件と誤判定した**。PR #134で修正。個人研究用取得はAES鍵＋正しいオーナープロファイルを条件に判定し、独立したプロバイダー向けJSON提供経路は従来の権利・真偽検証を維持する。
- PR #134のmain実行 `42927694949` は、API関連4設定未登録で `EXISTING_OWNER_PUBLIC_PAGE_RESEARCH` を確認。既存取得処理は当日の開催84Rを認識し、候補13レースの部分出走表を非公開一時領域へ取得。元ページGET回数は146、完全な4モデル予想保存は0件。これは正式予想成功ではない。
- 個人研究用候補は完全なモデル入力でも、機械取得に対する提供元の独立許諾でもない。欠測の必須項目をゼロ・平均・推測で補わず、候補を `pre/` 正式キューに混ぜない。サービス側の制限・拒否（403/429等）を回避しない。
- Public維持、GitHub-hostedのみ、既存4モデル・SHA原本・AES暗号保存・別runner読戻し、後付け予想禁止は変更しない。

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

## 固定したPR71ソースを新しい検証済み版へ更新（2026-11-10）

- GitHub-hosted main producer/読戻しの既存 pinned source を旧 `60b739bfb…` から既存 Draft PR #103 のHEAD `1b50a851726f3e061757fa670687af4c211c9005` に固定更新。mainコードを引き続き実行本体として維持し、未審査のブランチ先頭を追跡しない。
- 固定先の差分は出走表の累積着順率の誤計算修正、観測できるH/年齢/期別/明示単位風速の取込、既存4モデルのGitHub-hosted AES/結果照合合成試験と不足項目分類に限定。実モデル重み/元データ/権限を変更しない。元 source HEAD の347検査・既存4モデル保護とGitHub AES復元を再実行する。
- 公開 source probe は不足モデル項目の種類ごとの件数を出すが、個々の選手数値/名前/元オッズ/HTMLは絶対に記録しない。
- これはCIで検証した固定SHAの昇格であり、実レースの許諾・全93必須入力・公式結果・本番AES世代を作るものではない。SOURCE_FEED_NOT_CONFIGURED と未確認の本番はHOLD。

## 結果改訂の既存本番経路への接続（2026-11-10）

- 公開GitHub上の既存Ubuntu実行は、予想源を固定した `9604fa4a047b4e0c2a7687a5356d975013413924` に更新。旧固定 `1b50a851726f3e061757fa670687af4c211c9005` は変更履歴として保持。固定SHAの先にあるモデルの係数・認証許可を自動的に変更しない。
- 既存の「認可済み同一JSONエクスポート1回GET」へ、オプションのV3結果 `RACE_AI_KEIRIN_LICENSED_PROVIDER_EXPORT_V3` を追加（`deliveries`, `odds_snapshots`, `result_observations`）。結果目的 `result_collection` および `result_analysis` は台帳の実ソース許可に明記されていなければ受け入れない。結果用の別サービス、別有料APIや秘密設定は追加しない。
- 結果は本物の事前PR71四モデル原本の存在、レースID、車番、発表/捕獲時刻と販売締切の後先、提供元改訂IDを照合し、既存 `PrivateKeirinStore.add_result_observation` と `FourModelRankLedger.replay_all` に接続。既存結果を予想へ混ぜない。結果の元ソースSHAは私有SQLiteに保持し、同一改訂の繰り返しは二重加算せず、異なる訂正は追加改訂として残す。
- 公開ログは新規結果改訂件数・保留件数のみ。結果の詳細、払戻額、予想原本、ライセンス資料はGitHubの平文に出さず、AESで密封した既存Git履歴にのみ格納（実データ投入は未達）。
- URL・ローカル許諾資料のSHA照合は提供者の公式結果署名の独立認証ではない。 `official_result_independently_authenticated=false`、正式成績は未確定のまま。最優先は今なお真の許諾済み必要93入力枠、実際の4モデル事前凍結、暗号保存独立読戻し、主催者公式結果・訂正の独立認証。
- synthetic CIで架空の4モデル事前原本→既存AES Git世代→結果到着→既存PDCA 4モデル→次世代暗号保存→別読戻しを実行。実レースの到達証明ではない。
