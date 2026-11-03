# RACE-AI | 競輪結果の取得→改訂履歴→PDCA接続: PR #72用実装スライス

## 構築範囲 (2026-11-03)

`race_ai/keirin_result_delivery.py` は**提供された**KEIRIN正規化結果を既存
`evaluation_result_revision_bridge.link_result_revisions` が受け取れる
`RACE_AI_OFFLINE_RESULT_OBSERVATIONS_V1` へ変換する。既存の予想モデル、
改訂管理、スコア計算、独立時刻レシートを作り直していない。
`research_hit8` は参考照合のみ。正式的中率は常に `null`。

入力源は実装中では GET しない。許可済み提供ファイルまたは契約済み配信を
**所有者の秘密ランタイムで独立に認証した**バイト列と、別々に審査済みの用途別
権利レコードが必要。JSON に `approved:true` と書くだけでは権利付与にならない。
形式上の `admission` 辞書は権利・原本を機械的に結び付けるインターフェースであり、
暗号署名や権利者の契約をこのモジュール自体が認証したことにはならない。

### 入力コントラクト

- 既存PR #72の `RACE_AI_FOUR_SPORT_COHORT_BRIDGE_V1`（対象日・レースID）
- 日付単位の正規化バイト列 `RACE_AI_KEIRIN_NORMALIZED_RESULT_DELIVERY_V1`
  - `event_date_jst`, `source_url`, `source_published_at`, `captured_at`, `results`
  - 1件ごとに `race_id`, `starters`, `official_cutoff_at`, `status`,
    `winning_triples`, `payouts_100yen`, `refund_status`, `provider_revision_ref`
- 所有者の信頼できるランタイムが付与した `admission`：`source_id`, `source_url`,
  `source_sha256`（投入バイトSHA-256）, `rights_ref`, `verified_purposes`
  (result_collection/private_retention/result_analysis), `checked_at`, `expires_at`
- `--previous-batch` は既存のバッチを読み取り専用で渡す。

`source_url` は KEIRIN.JP のHTTPSドメインに限定。ただしドメインが公式であるだけでは
内容の真正性も利用許諾も確立しない。契約配信が別ホストの場合は、接続方式を
権利者・提供元の規約に従って**審査し直す**。単にホスト一覧を広げない。

### 安全ゲート

1. 権利・原本ハッシュ・取得時刻・情報公開時刻・対象日・レースIDが揃わなければ停止
2. 元の締切後に結果を観測する。確定前、取消・非発売、失格/同着/返還は区別
3. 3連単の着順と100円払戻は組番単位で一致させる。出走していない車番は拒否
4. 同一バイトの再受信は新しい改訂として保存しない。結果訂正は参照ハッシュを結んで追記
5. 原本の締切前予想と混ぜず、予想の追加・変更・自動昇格をしない
6. 実測の全対象Hit@8は、全対象母数・公式結果権限・個別外部時刻の予想レシートが揃うまで `null`
7. 4MiB/100レース上限、CSV無断大量取得やブラウザ自動スクレイピングなし
8. 出力は `O_EXCL` による新規作成、所有者だけ読める0600モード、秘密データを公開PRに載せない

### 実行例（既に許可済みデータを受領したランタイムのみ）

```bash
python -m unittest discover -s tests -p 'test_evaluation_keirin_result_delivery.py' -v
python scripts/keirin_result_feed_once.py \
  --bridge /owner-private/bridge.json \
  --feed /owner-private/keirin-result-delivery.json \
  --admission /owner-private/reviewed-receipt.json \
  --previous-batch /owner-private/earlier-batch.json \
  --reference-forecasts /owner-private/forecast-reference.json \
  --output /owner-private/research-result-20261103-01.json
```

出力exit code 2は**研究用に変換・監査結果を保存できた**印。正式な結果認証済みという意味ではない。
実際の `source_published_at` を取得時刻から創作しない。未知の場合は `null`。

## 残る本番完成ブロッカーと次段階

- **第一関門：** KEIRIN.JPまたは認可されたデータ提供者から、レース結果・払戻・訂正の
  機械取得、非公開保存、分析・モデル学習、許容アクセス頻度、料金、利用期間の明示的な用途別権利と、
  安定したデータ配信経路を取得。現時点で認定済みは無し。公式サイトHTTP200は許諾ではない。
- **第二関門：** 当該データの本物の取得/受信とソースハッシュを、所有者ランタイムの
  外部証明と共に受信する。監視は許可された更新通知/Webhookまたは契約フィード限定。
- **第三関門：** PR #72の結果改訂/PR #71の `pr64_pdca_cycle.py` および
  `permissioned_source_delivery.py`, `cutoff_job_queue.py` と明示的な橋渡し。
  同一未来レースで旧モデルと新モデルを別々に締切前凍結し、改訂済みの公式結果で比較。
- **第四関門：** GitHub Actions等の永続実行・私用保存・失敗時復旧を実レースで実証。
  時間遅延・バッチ欠落・未予想を台帳へ残す。自動投票、課金、一般公開、本番統合は別途承認。

このPRは**実装コード＋合成試験**であり、正式なリアルタイム全国自動結果取得、
正式Hit@8、24h無人運転、main統合、製品完成を意味しない。

確認した公式利用ポリシー：
https://keirin.jp/pc/dfw/portal/guest/policy/index.html