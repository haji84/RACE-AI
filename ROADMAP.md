# RACE AI execution order

1. P0 access: resolve the precise Preview-only OIDC rule rejected by Vercel's Trusted Sources API. Keep SSO on. Run exact-head Actions probe, private write/read SHA/delete, reject unauthorized/date-mismatch data. Record actual proof.
2. P0 data: establish separate factual ingestion/publication rights; implement Tokuyama dated program-detail retrieval and reconcile registration IDs/motors/meet for12R/72boat entries; authorized worker→private Blob→/api/today→phone. Extend current-day schedule coverage to24venues; distinguish unknown, failed and no-event.
3. P0 UI:8reference images, phone and desktop layouts, automatic feed, home/all-races/details/tickets. Browser tests with synthetic fixtures are separate from real data and actual iPhone Safari.
4. P1: official B/K original acceptance, player/motor histories and periods, actual-course ST5/10/20 and separate frame10, win/loss contexts and front-entry resistance, exhibition/odds/weather time series, safe shared money engine and budgets.
5. P2: baseline joint120 outcomes (6boats), entry scenarios, calibrated probabilities, EV and0-point skips, immutable pre-start predictions, official settlement and recommended-vs-actual scoring.
6. P3: licensed private video pipeline/quality labels, tracking and relative motion, model ablations, time-ordered untouched evaluation, reproducible learning/update/rollback.
7. P4: account isolation, admin operations, monitoring/cost limits, independent backup and tested restoration, security/load/UI audits, terms/privacy/manuals, concrete release evidence and user release decision.

Parallel work: data/UI/security first; shared contracts have one owner. Keep changes reviewable and avoid duplicated engines. External rights/access blocks do not stop unrelated safe changes.

## 2026-10-21 4競技・Actions中心アーキテクチャの追加（PR #61提案）

正式差分: `docs/RACE_AI_ACTIONS_CLOUD_DELTA_20261021.md`、Goal: #67、最優先実装: #68。

- P0-A: PR #59〜65/KEIRIN-AI PR #1の再利用・依存・実証を棚卸しし、用途別ソース権利マトリクスと4競技データ契約を確定。
- P0-B: 既存ボート収集/予想/評価を再利用し、4競技の合成E2E（発見→締切前オッズなし凍結→結果改訂→PDCA）と保護CIを実証。
- P0-C: 承認された公式データで少なくとも1競技1レースを実E2E。4競技全てを完了扱いするには各競技実E2Eを別々に証拠化。
- P0-D: ZBookなしでActions定期実行→private保存→再開・欠落検知→締切前凍結→結果照合を実測。Cloudflare/別クラウドは要費用・安全・既存Preview互換性検証後に採否判断。
- P1: 四競技ごとに欠測/時点/特徴量の品質、精度と回収の前向き比較、iPhone UI実機試験を実行。

本項は従来P0のPreview/OIDC/Blobおよびボート24会場実証を置き換えて捨てるものではない。**依存順位を再計算して統合する**。実装・運用は未完であり、提案文書だけを完成証拠にしない。

## 2026-10-21 98%挑戦GOALを含む統合P0優先度（PR #61提案）

根拠: `docs/RACE_AI_98PCT_GOAL_AMENDMENT_20261021.md`、`docs/RACE_AI_ACTIONS_CLOUD_DELTA_20261021.md`。
実行指示: `docs/CODEX_INTEGRATED_PRIORITY_20261021.md`、Issue #67/#68。

1. 正確なSHAで既存未統合資産と53章要件を棚卸しし、オッズ由来特徴/券点数/競技対象/ランタイム差分を `SPEC_CONFLICTS.md` に記録。
2. 既存ボート実装から安全に共通契約を抽出し、合法データ/全レース台帳→市場情報なし全3連単Top8→締切前append-only凍結→公式結果改訂→全対象Hit@8の合成4競技E2Eを完了。
3. Actions中心でZBook非依存の永続保存/冪等実行/未処理回収/締切遅延/復旧を正確なheadと実runで実証。既存認証/Preview/Blobを再利用しProduction/Cloudflare移行は未承認のまま。
4. 許諾確認済の4競技公式データに順次接続して実レースE2Eを競技別に検証。未達・未予想を隠さず捕捉率を提示。
5. 外れ原因分類→候補改良→時系列評価→同一未来レースの並走→昇格/却下/ロールバックを実装・前向き実証する。98%は未達の挑戦目標で、300件は初期検証に過ぎない。

旧工程（既存OIDC/ボート/UI/映像）を破棄するのではなく依存順で整理する。主指標はコードやPR数ではなく完成済受入条件・全対象レースの的中率・実測品質。仕様作成のみを完成としない。
