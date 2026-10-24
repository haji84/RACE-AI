# P0: 事前予想ハッシュの外部時刻証拠と4競技の実データ接続ゲート

記録日: 2026-10-23 (JST)。参照 Issue #67/#68、Draft PR #69/#71/#72。**契約テスト成功≠実予想完成**。

## 1. このブランチで実装したこと

`race_ai/github_freeze_receipt.py` は `verified_event_projection.project(..., verify_freeze=...)` に渡せる検証関数 `verify_github_freeze` を提供する。独立した時刻はローカルの `generated_at`、`persisted_at`、Gitコミット日時ではなく、GitHub APIが返す**pushまたは同一リポジトリPRトリガーのActions run.created_at**とする。

検証時、GitHub HTTPS APIから run IDに対応する run を取得し、`event=push`、同一リポジトリ、`created_at < 公式締切` を要求する。runの `head_sha` に固定して `audit/freezes/YYYY-MM-DD/<race>.json` を読み戻し、JSONに含まれる `prediction_sha256` と `cutoff_at` が検証対象に一致するときのみTrue。ブランチ最新内容や自由入力の `receipt_verified=true` は証明に使用しない。

アンカーファイルの最低限の形（ダミーのハッシュを本番入力に流さないこと）：

```json
{
  "schema": "RACE_AI_GITHUB_FREEZE_ANCHOR_V1",
  "race_id": "boat:venue:2026-10-23:1",
  "prediction_sha256": "<64桁の実際のSHA-256>",
  "cutoff_at": "2026-10-23T12:00:00+09:00"
}
```

後から取得した `run_id` と、このアンカーの保存先`path` をレシート参照として付与。予想本文のハッシュ算出後、**公式締切より十分前**にGitHub上へアンカーを保存し、そのコミットを対象とするpush/PR runがGitHubサーバーに締切前に作成されたことを確認する必要がある。後付けの`receipt`情報で元の予想本文や買い目を書き換えてはいけない。

**未完の注意点**
- 既存PRの契約テストに `audit/freezes/**` を監視対象として追加した。ただし、実予想保存writer、予想のハッシュからrun-idへのレシート連携、実レースの受領レシートは **未接続**。このモジュールだけで「凍結済み」と判定しない。
- GitHubサーバーが記録する時刻と内容指紋の照合であり、第三者のRFC3161署名や絶対的改ざん不可保管の証明ではない。外部時刻サービスの信頼評価は別途必要。
- 共通projectionのcallbackはレースIDを引数に受け取らないため、レースID/入力スナップショットとアンカーの**完全な独立照合**の拡張・受入テストが別途必要。
- 全レースで1件ずつActionsを発火すると実行数・遅延・費用の問題がある。候補は締切帯ごとのバッチ保存＋同じcommit SHAのrunタイムスタンプ共有。時刻遅延とGitHub Actions実行枠は測定してから採用する。
- PR #64の STOPPED_UNCERTAIN_POST / nonce は一切再利用しない。

## 2. 4競技ソースの確認済み入口と未達ゲート

| 競技 | 実在する一次情報の入口 | 自動取得/保管/学習権限 | 接続状態 |
|---|---|---|---|
| ボート | [公式ダウンロードページ](https://boatrace.jp/owpc/pc/extra/data/download.html)の[B番組表](https://www1.mbrace.or.jp/od2/B/dindex.html)と[K競走成績](https://www1.mbrace.or.jp/od2/K/dindex.html)のリンクは2026-10-23に存在を再確認。[2025-03-05終了告知](https://www.boatrace.jp/owsp/sp/site/news/2025/03/41685/)の対象は「閲覧」等であり、B/Kダウンロード終了を断定できない。個別LZHの実通信・中身は未検証 | 自動取得/保管/AI解析/学習/派生公開は用途別に未確認 | 接続停止（権利未確認） |
| 競輪 | KEIRIN.JP公式サイト、仕様/許諾はPR #72権利表参照 | 未確認 | 未接続 |
| オート | AutoRace.JP公式レース結果案内 https://autorace.jp/support/faq1006/2024/05/26/035329/ | 未確認 | 未接続 |
| 競馬・中央 | JRA https://www.jra.go.jp/use/index.html | Web閲覧と自動利用の同一許諾は確認できず | 未接続 |
| 競馬・地方 | NARのダウンロード案内/規約はPR #72権利表参照 | 自動保存・学習利用の許諾未確認 | 未接続 |

**公開閲覧が可能**と**サイトに負荷を掛ける自動取得や原本の再利用が許可される**は別。新規取得・保管・学習は用途ごとの正規確認を経るまでは当該ソースで停止。PR #72の人手で供給する二系統照合は実ソースの完全性保証ではない。競技全対象数と取得可否はUNKNOWNとして保存し、`0レース開催` に読み替えない。

## 3. 次の真正な受入実験

1. 4競技それぞれ、**実際に許可される提供経路、用途、頻度・保存条件・費用**を記録し、個別に取り込む。先に許諾が確認できたソースだけで始める。
2. 許可された出走情報と公式締切の実値を時点付きで取り込み、レース総数・欠測と時刻の証拠を比較する。
3. 未来の1レースについて `snapshot-hash→odds-free top8→prediction-hash→GitHub push-run anchor→readback verification` を実証。GitHub created_atが締切以降なら予想的中計上禁止。
4. 確定結果・返還・払戻を権利確認済み経路で照合して前向き実測を残す。正式KPIは全対象の欠測も分母に含める。旧予想と次期改善候補は別バージョンで未来同時比較する。

現時点で4競技実取得・独立時刻付きの実予想証拠・全レース捕捉・実測Hit@8は **未実証**。自動投票、有料契約、公開配備はなし。
