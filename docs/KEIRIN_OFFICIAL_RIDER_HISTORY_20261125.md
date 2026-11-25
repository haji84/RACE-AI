# 保存済み公式結果からの私有選手履歴（未配備・停止保存）

2026-11-25、ユーザーの作業移動・停止指示により、main 起点の小さい変更を未マージで保存した。開発再開の指示を受けるまで本番実行・マージは開始しない。全体引継ぎは既存 [Draft PR #327](https://github.com/haji84/RACE-AI/pull/327) の `docs/KEIRIN_PAUSED_HANDOFF_20261125.md` に保存する。

既存の公式原本・結果・暗号化アーカイブから出典を再解析し、登録番号ごとの最新の適格着順を既存 `Ride` / `HistoryBook` に渡す。訂正を一走として数え、落車等・同着・訂正履歴は私有情報として残す。新しいモデル、状態の正本、PDCA、鍵、権限、スケジュールは作らない。

## 変更

- `race_ai/keirin_official_nationwide_records.py`：固定 index commit の読み取り専用選択と既存 replay の等価な抽出。
- `race_ai/keirin_official_rider_history.py`：利用可能時点、公式出走者、訂正の出典と時計を確認する履歴投影。
- `scripts/keirin_rider_profile_history.py`：既存研究側の集計器を無変更で含める。残存期間や同日結果の扱いを新しく作り直さない。
- `scripts/keirin_official_rider_history_readback.py` と2つの新テスト：固定 index／暗号文を鍵のない段階で検証し、私有履歴を0700/0600へ保存。公開は集計のみ。
- 既存 `keirin-rider-dossier-readback.yml` 内に、公式履歴専用の契約テストと保護 main 読戻しを追加。公式履歴の読戻しは既存 `RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED` が `true` の場合に起動し、暗号文を先に検証してから既存 RSA secret で再生する。権限は `contents: read`。公式履歴の artifact は集計だけの safe report とし、従来のカルテ復元とは独立に実行する。

## 検証状態と未完了

修正前の関連95テストが通過。独立レビューで固定 source receipt の末尾改行不足を発見し、既存 canonical encoder で修正した。実際の receipt を本番と同じ parser で読む回帰を加え、最終修正後の CLI 9テストを通過した。停止保存時点では、最終変更後の全体再実行とGitHub CIは未実施だった。

Macの分離worktreeで関連186テストが通過した。既存カルテ復元とその契約テストはmainと同じ定義で、公式履歴の読戻しだけが既存の許可変数で制御される。固定GitHub URLからindexと7暗号文を読み戻し、SHAとヘッダーを再検証した。GitHub CIと実鍵での再生は未実施。

固定先は `official-rider-history-source.json`。原本4件・結果2件・保留0件を要求し、空の成功を拒否する。独立レビューで実際の7暗号文のSHAとヘッダーが一致した。実 owner-key runnerでの2件の平文再生と結果件数確認は未実行。新runnerの35秒上限のGit fetch（約400MBのstate treeを含む）は未検証。

これが通っても全国カルテ自動更新、未来予想の真正性、展開予想の的中、精度向上の完成証明ではない。実日付付き台帳との結合、翌日の窓更新、本番定期運転は既存研究側の次工程。元の結果や予想を変更していない。
