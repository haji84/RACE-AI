# RACE-AI 競輪: 永続ディスク上の自動PDCAスプール

## 実装と未実証の区別
保護された永続ディスク上で、各レースの出走前入力が届くと、実際のPR71モデルで3連単8点を生成、SQLiteに原本を一度だけ保存。結果入力が届くと確定後データを別履歴として記録し、同じ元の8点と比較。次の出走前入力があれば自動で次予想へ進む。毎回人間の次工程指示は不要。
今回のE2Eテストは架空レースと私的受領証明。2026-11-03の76レースを実データで無人完走した証拠ではない。

## オーナーの永続実行環境での起動
必要なディレクトリを永続ディスクに作成し、以下のコマンドを実行する。
```bash
mkdir -p "$HOME/.race-ai/private/daily" "$HOME/.race-ai/private/pre" "$HOME/.race-ai/private/results"
python3 -m scripts.keirin_private_agent --db "$HOME/.race-ai/private/owner.sqlite3" --inbox "$HOME/.race-ai/private" --personal-only --loop
```
daily/*.json: RACE_AI_KEIRIN_ALL_DISCOVERED_RACES_LEDGER_V1、全レースのIDと未予想を残す。
pre/*.json: RACE_AI_KEIRIN_PRIVATE_PRE_RACE_V1、各選手の必要な実数値・ソース・公開時刻が揃わない場合は予想をスキップする。
results/*.json: RACE_AI_PRIVATE_KEIRIN_RESULT_OBSERVATION_V1、結果訂正を別履歴として保存する。
120秒おきに監視。処理済み原本は上書きせず、既存結果の再観測による重複カウントを防止。
GitHub-hosted runnerのエフェメラルディスクで実行した場合は、専用永続ボリュームの明示がなければ停止する。

## 検証証拠
https://github.com/haji84/RACE-AI/actions/runs/41578066110 : PR71の実コードとSQLiteによる架空2レースの前予想→保存→結果→PDCA→次レース予想と再起動テスト。
https://github.com/haji84/RACE-AI/actions/runs/41578235968 : 上記に加えCLIの情報源境界・使い捨てディスク拒否テスト。28/28件成功。

## 未完成の運用条件
1. 実際の76レース分の出走前データをprivate inboxへ自動供給するフィード。現在はデータが自動流入しない。
2. 出走全選手と環境の必須特徴量の事前実測・時刻認証。数値不足を架空値で埋めない。
3. 独立した公式確定結果と返還・同着・訂正の接続。第三者掲載値のみでは正式Hit@8を出さない。
4. 安全な永続ホスト上での実運転と予想SHAの締切前外部時刻証明。パブリックGitHubへ非公開原本を載せない。
5. 実際の全対象レースの見送り・未予想を含めた成績、A/B未来比較、再起動・障害復旧の実証。

本機能の状態は SOFTWARE_CONTRACT_E2E_SYNTHETIC_PASSED / REAL_RACE_AUTOMATION_NOT_DONE。mainへの統合だけで本番稼働したと主張しない。
