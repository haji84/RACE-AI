# BOAT 展示後予想・自動実行の段階導入（PR #71 に追記）

## 現在地（2026-11-03 JST）

- **実装したもの:** `race_ai/exhibition_autorun.py::tick`、`tests/test_exhibition_autorun.py`。既存の`cutoff_job_queue.plan`と`boat_multi_feature_models.run_models`を再利用し、締切早い順の検査・展示不足の停止・読戻し先行・2分以上の安全余裕・1実行あたりの収集上限・POST不確実性の停止を行う純粋な制御層。
- **未実装:** 当日全場実フィードからの`records`生成、許可された展示値と履歴・天候の収集／正規化、署名付き用途別許可の照合、永続的排他`claim`、OIDC付き`submit`、外部保存レシート`verify`、失敗の継続監視、スマホ配信と通知、正式モデル校正・独立レビュー・本番の常時起動。
- **稼働状態:** `live_scheduling_enabled=false`。単体・合成テストを通しても実レース展示後の自動発行が始まったとは判定しない。
- 既存PR #64/`codex/race-ai-completion`は**変更しない**。未解決POST／nonceを再送せず、保護されたPreviewと非公開Blobの既存運用を温存する。
- PR #71にはすでに4競技予想UIと別モデルがあるが、未校正推定値は検証済み的中確率として表示しない。自動投票・一般公開・課金・Production変更は対象外。

## 接続契約

`tick(records, clock, readback, acquire, claim, submit, verify, max_collect=12)` に運用アダプターを注入する。プロバイダー通信・権利認定・永続保存と計算の責任を分離する。

1. **records:** 正式な当日レース台帳。少なくとも `race_id, sport="boat", cutoff_at, cutoff_verified=true, source_permission_approved=true`。未確定締切と未許可は成功扱いにしない。JSTの開催日と締切が同じレースかをアダプターで検証する。
2. **readback:** 一意キー `(race_id, phase=post_exhibition, model_version)` の保存状態を読取専用確認。`ABSENT / CLAIMED / UNRESOLVED_POST / VERIFIED` のみを返す。通信不能・状態不明ではPOSTしない。`VERIFIED` は本物の保存レシートを確認した場合に限る。
3. **acquire:** 署名・期限・用途別権限を確認したプロバイダーから、同一レース6艇の実展示と学習に必要な実データを取得・出典／捕捉時刻付きで正規化する。戻り値は `status: AVAILABLE|PENDING|UNAVAILABLE|RIGHTS_BLOCKED`。AVAILABLE時だけ `snapshot`, `source_rights_verified=true`, `exhibition_identity_verified=true` を付与。**署名の真正性をこの制御層が証明するわけではない**。
4. **claim:** 公開先ではない非公開永続ストアで一意キーを原子的・作成限定で予約する。二重同時実行は一方のみ`CREATED`。古い`CLAIMED`や`UNRESOLVED_POST`を勝手に解放・再送しない。
5. **submit:** 既存のスコープ限定OIDCで、予約のある1予想のみ非公開に保存する。リクエストが送信された可能性があれば再POSTしない。送信成否不明を記録する。
6. **verify:** 実保存先から`race_id`・`prediction_sha256`・`model_version`・外部時刻・締切・出典の固定レシートを読み戻して照合。成功のみ `FROZEN_READBACK_VERIFIED` とする。

## 自動稼働への移行順（実証ゲート）

1. **1会場12R:** 収集許可・完全性／時点安全を実データで検査し、展示未掲載／展示値不足／欠場・変更／開催中止の各ケースを欠測理由付きで台帳に記録する。実POSTに先立ち読戻し確認と排他動作を隔離環境で再現する。
2. **隔離された実E2E:** 一つの**新しい**対象レースで、実データ受入→展示更新→最大8点をオッズ非依存で計算→締切前の外部時刻付き保存→読戻しを成功させる。過去の不確実なnonceは再利用・再発行しない。
3. **クラウド常時実行:** 承認済みのジョブ・データ供給者の許容頻度・原価0円制約・同時実行排他・状態永続化・障害通知を満たす仕組みへ接続する。GitHub Actionsの`schedule`には**5分以上の周期制限、遅延や実行欠落の可能性**がある。全展示後の締切前発行を保証するトリガーとして単独採用しない。
4. **全国展開:** 24会場の開催有無／全レース／出走変更を締切順に取り込み、全件分母・展示取得率・締切前成功率・未予想理由を集計する。重複・未解決POSTは停止してアラート。スマホ通知は利用者の同意を取った専用経路で実装する。
5. **精度検証:** 既存の展示前版と展示後版を同一未使用レースで締切前に別凍結し、Hit@1/Hit@8・Brier・校正を前向き比較。現行`boat_multi_feature_models`は未訓練・未校正なので、生のscoreを検証済み的中確率と称しない。

**完了判定:** 対象全レースと分母、実収集時刻、外部永続保存レシート、実機での表示、実結果照合の証拠が揃うまで「展示後予想の完全自動運転は未達」。PRの変更は既存PR上に集約し、main統合・公開・費用・権限拡大は別承認と独立確認の後に限定する。
