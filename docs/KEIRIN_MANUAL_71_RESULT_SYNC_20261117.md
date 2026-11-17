# 競輪 2026-11-17 全71R：ChatGPT手動予想の結果自動照合（研究専用接続）

## 目標と現状
既存RACE-AIに、11月17日の会話内手動予想71レース（7会場）を**変更せず**取り込み、既存GitHub Actionsで認可済み結果原本が得られた後に「結果改訂の取得 → 3連単全順位照合 → 会場別／信頼度別／波乱警戒別集計 → HTML表示」を自動化する。

**本改修の合格範囲**：SHA連鎖した手動予想 v2/v3 と、既存PR71の許可済みV3結果正規化スキーマを用いた**ネットワーク不要の比較器**。検証可能な結果がなければすべて `RESULT_UNOBSERVED` として保留。公式結果の収集・独立認証・永続保存・サイト公開までの本番接続は**未完成**。勝手に完成と呼ばない。

### 手動予想原本（GitHubに平文で置かない）
- 会話で生成した v2 71R JSON：`keirin_2026-11-17_71r_tactical_ranked_v2.json`、ファイルSHA256 `3bdb6930812cd00035f5591cc4a349aa171d49a1f1a709c44a2f2b990c233c59`、公開時刻 `2026-11-17 08:42:31 JST`。
- 12点拡張 v3 71R JSON：`keirin_2026-11-17_71r_12point_expanded_v3.json`、ファイルSHA256 `4cd7e88d9ab7880702180bcbab248ebda2a8078a721fab5a08fe47323de21d68`、公開時刻 `2026-11-17 09:06:03 JST`。`baseline_v2_sha256` は v2の実ファイルに一致。v3 第1候補と v2 第1候補は全71レースについて一致。追加候補は既存買い目の後にのみ記録。
- 利用者向け「信頼度高め15R／波乱警戒13R／その他43R」HTML：`keirin_2026-11-17_71r_by_confidence_and_upset.html`、ファイルSHA256 `2c0ec7ed2f8b77b81e026ae162ba4b185abcc4d1983e624d08eef7e61c1cf11c`。
- v3の一部レースでは `prior_research_first` と実際の `ranked_picks[0]` が一致しない（例：小松島8R、9Rなど）。**過去の説明用フィールドではなく、SHA認証した v2 ranked_picks と v3 ranked_picks が一致することを厳格確認**し、補正や後付け置換をしない。
- どの保存時刻も独立に確認した**正式発売締切時刻の証拠ではない**。各レース発走予定の後に追加された買い目を参考事前評価から除外するが、「発走前＝締切前」とは主張しない。

## 新コード
- `race_ai/keirin_manual_result_sync.py` : 71Rの原本とSHA・順位・追加点数を検証。既存 `RACE_AI_KEIRIN_LICENSED_RESULT_REVISION_V1` に準拠した、すでに許可を受けてプライベート領域に置かれた結果候補を読む。結果改訂番号の不一致・改竄・別日/別会場を拒否し、的中順位、Hit@1、Hit@全点、100円均等購入の仮想払戻額を会場・区分別で計算。結果未取得は母数に含めない。断定的公式判定、正式PR71成績・実購入収支と混同しない。
- `scripts/keirin_manual_result_sync_cli.py` : GitHub Actionsの既存安全境界で実行する、入出力先を `GITHUB_WORKSPACE` の外に限定したCLI。私有テキストHTML／JSONレポートを mode 0600でcreate-once保存。標準出力は件数とHOLD状態のみ。
- `tests/test_keirin_manual_result_sync.py` : 71R、出力の保持、結果の改訂矛盾、SHA破損、返還、未照合、発走後追加点除外、HTMLをJSなしで表示、正式的中率の詐称禁止の合成テスト。

## ローカル/信頼済みrunnerでの呼出し（例）

```bash
python -m scripts.keirin_manual_result_sync_cli \
  --forecast "$RUNNER_TEMP/private/manual71-v3.json" \
  --baseline "$RUNNER_TEMP/private/manual71-v2.json" \
  --forecast-sha256 '4cd7e88d9ab7880702180bcbab248ebda2a8078a721fab5a08fe47323de21d68' \
  --categories "$RUNNER_TEMP/private/manual71-classification.html" \
  --template "$RUNNER_TEMP/private/manual71-classification.html" \
  --result-dir "$RUNNER_TEMP/private/authorized-inbox/licensed_result_rows" \
  --out-report "$RUNNER_TEMP/private/manual71-result-audit.json" \
  --out-html "$RUNNER_TEMP/private/manual71-result-view.html"
```

**注意**：この経路を public Actions artifact や GitHub公開ブランチに平文でアップロードしてはいけない。上の `authorized-inbox` は元の公式結果取得元を**偽造せず** `keirin_licensed_result_stage.py` の既存許可チェックを通った行だけを入れる想定。これは独立した公式結果署名の検証ではなく、判定は一貫して `参考・未認証`。`GITHUB_WORKSPACE` 内に入力・出力があれば停止。

## 残る本番ゲート
1. ユーザー承認済みの既存AES-256-GCM保存・Git履歴へ、今回の v2/v3/分類HTMLを一度だけ**暗号化**して登録。既存鍵を公開・再生成しない。別runnerによる暗号文/原本SHA読戻しが必要。現時点では会話のファイルはGitHub側の非公開原本ではない。
2. 既存Actions内の結果取込が公開可能な結果を取得できること、正当な取得範囲と `403/429` を守ること、公式の確定結果・同着・返還・訂正原本の真正性を確認すること。現在 `keirin_mobile_one_shot.py` は1ページの未認証候補しか返さず71R本番結果の提供元ではない。
3. 既存Producerで返ったプライベート `licensed_result_rows` と本比較器を同じrunnerで結合し、結果改訂をAES stateに追記して別runner SHA照合。ここは**まだ配線していない**。既存PR71の正式モデル予想が0件でも、この手動予想を正式モデル成績に混入させない。
4. 公式確定が認証できたレースのみ正式成績に採用。改訂イベントは上書きせず追記。公開サイトには認可された集計・表示だけを反映。GitHub Actions scheduleは秒単位の即時反映を保証しない。
5. **実レース71件の本番結果連続取得 → 暗号保存 → 独立読戻し → 予想照合 → 会場別HTML反映**の証拠が揃ったときに初めて自動化完了。0件ならHOLD。ChatGPT手動予想とPR71本番4モデルは分母を分離。

## 実行状況
- 本文書作成時、ソース無しの10合成回帰テストはローカルでPASS。GitHub ActionsのテストはPR更新後に確認する。
- 2026-11-17の本人提供ファイルをSHA検証し、71/71レースの v2→v3 順位付き既存候補一致、分類15/13/43の整合を確認。
- 本物の許諾済み結果原本はこの実行環境に無い。`results_observed_unverified=0`、`provisional_paired_races=0`、正式Hit/ROIはNULL、進捗は**コード統合の研究段階**。
