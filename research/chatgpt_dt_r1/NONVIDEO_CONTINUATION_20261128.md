# 2026-11-28: 映像学習を待たないDT-R1継続方針

所有者の今回指示に従い、映像は逐次追加・学習する独立工程。新規映像ゼロや録画許可の状況を他工程の停止条件にしない。実測が欠けた潜在能力・消耗・6局面を「実測済み」にしない。実測用の受入条件は緩めず、映像あり/なし比較は別の評価として継続する。

優先順: (1) 初回のDT暗号原本の永続保存と締切証拠→公式結果照合、(2) A/B各50%の統合定義を実装とpinで確認しCodex/DTと同じ資料・固定点数で未来対戦、(3) B候補および5機能の映像なし独立比較、(4) 公式登録番号の履歴接続・全国未取得/認証不足解消、(5) 信頼度校正・オッズ/払戻検証とPDCA。映像が増えるたびに別の候補を作り、映像なし対照より改善したことを検証。正式本番昇格・鍵/権限/スケジュール変更なし。

## 今回の実証
- [固定state](https://github.com/haji84/RACE-AI/tree/ad17c6edccaa2dc05497fc99c7c653a08fd37cf2/research/chatgpt-dt-r1/future/20261128/5e022092a35c0258954090c6f3d0f8fa14f03f22511b28d6aa9183f5a38c381c) から17暗号原本とmanifestの実バイトを取得し、first pinの18 SHA-256とbyte数に全一致。1,476,673 bytes。first pin SHAも固定した。
- [producer](https://github.com/haji84/RACE-AI/actions/runs/46082459814) 78登録、17生成・暗号保存、38原本不足・23source確認不足。[独立reader](https://github.com/haji84/RACE-AI/actions/runs/46083220254) 17読戻し、別runnerの実完了08:36:34 JST。締切15分前の計算では16候補、08:47締切の1件は除外（期限08:32）。この確認はログ/メタデータ/保存manifestの照合であり、既存の全artifact認証verifierをこのターン実行したとは扱わない。
- `future_retention_gate.py` を追加し既存 `verified_producer` / `verify_readback` へfirst pinと保存実バイトの一致を接続。合成テスト1本（正常1＋改変等拒否5）成功。正式な運用callerは固定archive commitのlineage確認・保護済みowner復号・公式原本/結果replayへ接続すること。このPRはそのcaller、実際の採点、実運用CI成功や3者対戦の代用ではない。


## 採点callerの追加（研究PR、運用未実証）
- 固定初回batchのみの `scripts/keirin_dt_r1_future_settle.py` を追加。外部固定first pin、保存時と現stateの同一バイト、Git lineage、認証済みproducer/reader artifact、実owner復号、固定462列の入力再現と凍結モデルの分布一致を要求する。全候補の再検証が終了するまで結果を開かない。既存official result replayの最新改訂を使用し、失敗時に旧改訂へ戻らない。全78登録を残し、結果未取得・同着・予測不足を区別して固定K成績を出す。動画取得、再学習、新規予測、provider GET、state書換え、払戻評価、本番昇格は行わない。
- 既存main限定手動observe-resultsの `dt-r1-settle` モードをDraft内に接続。既存のowner keyと権限を維持、スケジュール変更なし。CI/独立レビュー/main保護マージ/実owner実行/公式採点は別の受入条件。今回は実際の3者対戦や未来改善とは数えない。
