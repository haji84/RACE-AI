# RACE AI

ボートレースを優先対象とする、実データ・確率予想・資金管理・結果検証の開発リポジトリ。

## 現在の状態（2026-10-15）

- `codex/race-ai-completion` / [Draft PR #64](https://github.com/haji84/RACE-AI/pull/64)へ既存実装と完成開発を統合中。mainは公開承認前のため変更していない。
- 公式開催一覧とB番組表の当日自動取得、非公開Blob保存、当日API、PC・スマホ表示を実通信で確認。2026-10-15は24場の状態、13開催・156レース・936艇。
- [実行記録](https://github.com/haji84/RACE-AI/actions/runs/38617313415)で取得内容とAPI配信内容のSHA一致を確認。PreviewはVercel認証で保護。
- 7画面のUI、共有の金額計算、予想・結果の版管理、時系列学習・評価の研究基盤を実装。予測精度は実レースの未使用期間で未実証のため、AIの推奨買い目は未公開。
- 自動投票・決済は対象外。事実データの所有者確認と、写真・映像の権利を区別する。
- 完成条件と未達項目は[開発状況](docs/COMPLETION_STATUS.md)、実行先と次の工程は[運用状態](docs/OPERATIONS_STATE.json)を参照。

## ローカル確認

Python 3.12で`requirements-worker.txt`をインストールし、`python -m unittest discover -s tests -v`を実行する。
画面は`python -m race_ai.dev_server`で起動できる。配信データが未設定なら「未取得」と表示する。
公式取得CLIは標準でdry-run。承認された範囲で明示的に`--execute`を指定する場合だけ通信する。

時系列学習の契約は[学習・評価基盤](docs/OFFLINE_MODEL_TRAINING.md)、展示・オッズ・結果取得は
[公式更新Worker](docs/OFFICIAL_RACE_UPDATES.md)、計算は[金額契約](docs/MONEY_ENGINE.md)を参照。

## 開発方式

設計変更は原則として変更ブランチからDraft Pull Requestを作り、レビューと検証を経てmainへ統合する。設計と実装の完了判定を混同しない。
