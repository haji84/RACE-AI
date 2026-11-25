# RACE-AI 作業停止・移動用引継ぎ（2026-11-25 UTC）

ユーザーの「今やってる作業を別の所に移すから保存してから停止して」により、ここで開発と自動継続を停止する。完成・全国稼働・統計的な精度改善を達成したという意味ではない。ユーザーが移動先で再開を指示するまで、新しい実装、学習、本番実行、マージを開始しない。

## 正本と再開場所

- 正本は haji84/RACE-AI。既存研究・引継ぎは [Draft PR #327](https://github.com/haji84/RACE-AI/pull/327)。今回の追加もそこへ保存する。
- 確認済み main は `b7dd5e3bcabb1cda4fab18753551563d5d8bd839`（PR #338）。PR #330〜#338 は前工程でマージ済み。今回の変更は未マージで、本番へ反映しない。
- 公式結果からの履歴更新だけを分離した保存ブランチは `codex/official-rider-history-live-20261125`。main 起点のレビュー用変更で、既存 Draft #327 全体をマージするためのものではない。
- 最初に `AGENTS.md`、[27節＋追加6能力の正本](KEIRIN_DETAILED_DEVELOPMENT_SPEC_20261125.md)、[完成判定](KEIRIN_DEVELOPMENT_ACCEPTANCE_20261125.md)、[既存継続手順](KEIRIN_JOINT_FORECAST_CONTINUATION_20261125.md)、この文書、PR #327 の最新 HEAD と差分を読む。別の実行者による並行更新があるため、最新を取得し、通常の merge で全変更を保存する。force push はしない。

## この停止直前に保存した実装

### 1. 戦術観測から条件付き展開への接続（研究用・未配備）

- `race_ai/keirin_tactical_packets.py`：既存 `keirin_build_rider_dossiers._tactical_rows` の SHA・登録番号・車番・出典・時計の検証を共用化。既存ビルダーの呼び出し名は維持する。
- `race_ai/keirin_tactical_context.py`：レビュー済み資料と別途確認済みの SHA、および現在の出走者の検証コールバックから、対象 snapshot に結び付いた戦術情報を作る。対象日当日、遅いレビュー、矛盾、未確認の選手対応を保留する。
- `race_ai/keirin_rider_context.py` の `compare(..., tactical_context=...)` と `multi_stage_makuri_hypotheses(..., tactical_context=...)` へ接続。選手・攻防に過去の観測件数、未知・矛盾・信頼区間を添付する。既存 A/B の候補、支持重み、確率、原本は変えない。観測成功率を次走の確率へ転用していない。
- `tests/test_keirin_tactical_context.py` を追加。関連45テスト通過。現 snapshot の差し替え、本人確認なし、同日・遅い資料、未知・矛盾、無資料時の完全な予想不変を確認。
- この接続の独立コードレビューと、実際の非ゼロ観測を持つ入力による完走は未完了。レビュー済み原文 packet がこの環境には復元されていないため、存在するように報告しない。

### 2. 保存済み公式結果から選手履歴への投影（分離ブランチにも保存・未配備）

- `race_ai/keirin_official_rider_history.py`：同じ既存公式暗号化記録から、出典を再解析し、原本の出走者・車番・登録番号・締切と照合した履歴を作る。適格な最新訂正版を一走として数え、同着、落車等の非数値結果、訂正の根拠は私有データに残す。後から得た訂正は古い基準時点へ混ぜない。
- `project_day_for_dossier` は日単位のカルテ用で、実レースの締切や締切前原本の証明ではない。歴史的な参照時点と実際の再生時刻を区別する。着順を自力能力・走行速度・展開一致へ変換しない。
- `scripts/keirin_official_rider_history_readback.py`：既存 RSA を使う保護された runner 用。先に固定 Git index・暗号文 SHA・ヘッダーを検証し、復号した選手別履歴は0700/0600の私有ファイルへ保存する。ログと artifact は集計 receipt のみ。0件・部分保留を成功としない。
- 独立レビューで receipt の末尾改行不足を発見し、`keirin_official_run_history._canonical` で修正した。実際に保存する receipt を CLI と同じ parser で読む回帰テストを追加し、最終修正後の CLI 9テストが両 checkout で通過した。
- 修正前の分離ブランチで公式・暗号・履歴・既存読戻しの95テスト通過。最終修正後の全体再実行は行っていない。新規公式投影15テストと完全な合成 RSA／原文再解析経路を確認済み。合成テストは実キーでの本番証明ではない。
- 分離ブランチでは既存 `RecordStore` に固定 index commit の読み取り専用機能を追加し、既存 result replay を同じ処理のまま抽出した。既存 `scripts/keirin_rider_profile_history.py` を変更せず main 向けに含める。root の固定比較モデルに使う6ソース・13依存 SHA は変更していない。
- 分離ブランチの `.github/workflows/keirin-rider-dossier-readback.yml` だけを拡張。既存の owner opt-in 変数、RSA secret、contents:read、保護 main 条件をそのまま使用。新しいスケジュール・権限・鍵は追加していない。未マージなので本番では動いていない。
- 固定 source receipt は `docs/evidence/keirin-live-accuracy-closure-20261125/official-rider-history-source.json`。index commit `4a269de3357f6e5063b41f8051e91948879bb112`、index SHA `dc4d702f5b2f0f505063259d0f8a26de5d6d9ddcf984f8443a433e2bc697cf9f`、参照時点 `2026-11-25T16:00:00Z`、原本4・結果2・保留0を要求する。独立レビューで7暗号文の実際の SHA とヘッダーを確認した。
- この新しい投影の実 owner-key runner 実行、2結果の平文再生、GitHub CI、正式レビュー完了、マージはまだ行っていない。新 runner のアーカイブ fetch は35秒上限で、約400MBの state tree を含む最初の取得は未検証。制限・エラーを迂回しない。

### 3. 日付付きの履歴台帳（着手途中・研究用）

- `scripts/keirin_rider_history_ledger.py` と `tests/test_keirin_rider_history_ledger.py` を保存。
- 既存の集計カルテだけでは翌日に月別窓や直近N走を正確に再計算できないため、元の `Ride` / `HistoryBook` と同じ日付付き観測を、登録番号・レース・車番・着順・掲載役割・級区分・出典番号の私有投影として保存する目的。
- `build_ledger` と SHA 固定の `read_ledger` の最初の往復のみ実装。架空 SQLite による1テスト通過。
- **未実装**：`merge_official`、訂正・非数値訂正による旧着順削除の履歴、日別窓更新の対抗テスト、私有 writer/CLI、既存暗号化経路との接続。validator は `official_revisions={}` のみ受ける。新しいモデル・状態・PDCA の正本として使わない。
- 実211,212件の台帳 export は開始していない。台帳の新しい実データ成果物は存在しない。

## 実データ・精度の状態

- main の前工程で、全国2,416登録者の基本カルテを生成し、2,393人に211,212の数値着順を確認した。収録は2025-10-01〜2026-11-22の約14か月で、3年間や生涯全件を保有したという意味ではない。
- 公開画面の75レース・516出走に整合する着順別確率と履歴表示を接続済み。比較原本が真の締切前なのは10レースで、他65件の事後再現を前向き実績へ加算しない。
- 既知期間3,201件の三連単上位4点は928→947件。未使用未来10件は3→4件、二車単上位2点は双方3件。小標本で統計的な精度改善・全国稼働・展開精度の向上を証明したとはしない。今回の追加で新しい的中・回収率・精度改善は確認していない。
- 11月26日用の既存84レース・580出走・7方式は別途固定済み。ここで原本を変更しない。公開 receipt はあるが、この環境ではその平文原本・ID manifest を復元できていない。元の保存実行者の取得先が不明であり、receipt だけから予想を再構成しない。
- 今回確認した SQLite は30,713開催レース中、全員のIDと完全着順・Bがそろう25,422件。既存の厳格な入力と交差すると23,769件（学習17,832・調整2,738・既知の診断3,199）。H、反応時間、原文のレース別SHA、認証済み締切時計はない。新しく学習は開始していない。
- 316件の公式 H/B イベント投影は SHA `96f92fd381a4d97607138f51c631266d3eb0aee7bf540ddecc96c215e37b4285` の receipt のみで、原文 rows は未復元。
- レビュー済み戦術 packet は SHA `e7bfc12b7a4a31eba6367722a425a7f1bc035e2d11ae0fdbbd68dfe8cb559df2`、原文 manifest は `a3af9edc1b5f2b571e48981b2c4966421aa12d88633e99ac35b8a9ba27415174`。どちらもこの環境に bytes がない。表示用の4場面メモや公開説明で置き換えない。新6能力の確認選手は固定済み84件に該当せず、寄与を評価できる非ゼロ分母はない。

## 秘密を含まない復元手掛かり

- 既存カルテ＋公式現役 registry は、既存 RSA 暗号化記録 `state/keirin-encrypted-history@4a269de3357f6e5063b41f8051e91948879bb112` の既存 dossier recovery から復元する。詳細は既存 `rider-dossier-recovery.json` と main の保護された読戻し。鍵は export しない。
- 既存10件の比較原本 recovery は同じ state branch の `0cac8de34e516553debcd804f0188a2302c10ac0`。既存の暗号化原本・公開ログ・独立runner証拠を参照する。
- ローカルだけの補助データは `/workspace/scratch/keirin-public-historical-clatqrb5`、`keirin-official-registry-rlhvprre`、`keirin-basic-dossiers-zcof2_gw`、`keirin-accuracy-closure-20261125` にあった。新環境にあるとは限らない。平文データは GitHub に保存していない。
- 履歴 DB は既存公開 source `sumidatadayoshi/keirin-data@2a1260fb0940ad11160b56a36f9c24cc4fb2f6d2`。`keirin.db` SHA `1bdad22b9744c9c5563f7bb1af31875170a3e6b7f4b0dd73fba8f98d645d8fc4`、`keirin_2026q4.db` SHA `d915560877493816b90df8bcd5e7bdef45557f57100b4cd40a3d017cd959334d`。再取得しても当時の締切前入力と偽らない。

## 再開時の順序

1. ユーザーの再開指示と、保存後の最新 HEAD／PR／CIを確認する。まず今回の追加コード・未完了レビュー・台帳の途中状態を読む。
2. 分離ブランチの最終全体テストと独立レビューを行う。承認済み範囲の小さいPRとしてCI通過後に扱い、巨大 Draft #327 はまとめてマージしない。
3. 既存保護runnerで新公式結果投影の実復号を実施し、適格2件・保留0・実数値着順件数を確認する。失敗したら正確な停止段階を記録し、権限やアクセス制限を変えない。
4. 台帳の訂正・削除・時計・翌日窓のテストから実装を継続し、実データ export、既存暗号化保存、独立復元までつなぐ。集計値だけで翌日の履歴を正しいとしない。
5. 未復元の観測 packet と固定84件の本当の原本を探す。見つからなければ保留を明示し、架空のデータ・能力・確率を作らない。
6. 旧A/Bと同一時点・同一対象・同一点数で比較し、未使用未来の評価を続ける。CI、合成データ、画面、少数的中、履歴接続だけで27節の完成や精度改善を宣言しない。

Cloudflare/Vercel禁止、GitHub-only、既存鍵・権限・課金・原本・主催者アクセス条件の維持は継続する。今回の停止はユーザーによる移動指示であり、新たな外部制約が3ターン継続したという報告ではない。
