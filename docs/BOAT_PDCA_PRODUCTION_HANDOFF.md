# 実データPDCAの暗号化公開・GitHub復元

2026-11-06、オーナーの「進めよ」に対応して、実データ受入の経路を追加した。**鍵が実行環境へ渡るまで実データの公開・復元は完了しない。** この接続によるGitHub Secrets管理はHTTP403で拒否された。権限変更や別の認証情報での回避、既存鍵の置換、自動鍵生成は行わない。

## 追加した接続

`scripts/boat_pdca_github.py publish`は、所有者鍵を検査してから、同じ`haji84/RACE-AI`内の専用ref`state/boat-pdca-encrypted-history`へ暗号文だけを追記する。main/PRのrefや稼働workerは変更しない。

- fetch/pushの有効URLをすべて検査し、それぞれ1つの対象リポジトリに限定。その検査済みURLを各通信に固定する。
- 最初の公開だけ`--initialize`が必要。既存refの更新は、前に受け入れたcommitを`--expected-parent`で明示する。勝手に空状態へ戻さない。
- 前世代を同じ鍵で復号し、原本・全ファイル版・結果訂正・採点を失う更新や古いheadへの回帰を拒否する。履歴DB/選手DB等のhead欠落や参照不整合も、checkpoint/復元/公開時に拒否する。
- 世代別の暗号文/proofは作成専用。未登録の同名ファイルも上書きしない。通常の非force pushとremote head再確認を行う。
- 公開前に自分の暗号文を私的領域へ復元し、元bytes・予想再計算・物理保存レシート・既存採点の再実行を検査する。

公開先はGitHubの通常GitでありGit LFSや追加プランを使わない。既存codec同様に状態サイズには上限があり、無制限の全履歴保管や永久保存を保証しない。

## 所有者設定後の操作

所有者の32ランダムbytesをBase64化した同じ暗号鍵を、GitHub Actions secret`RACE_AI_STATE_KEY`と作業環境へ渡す。キーをコード・公開ファイル・コマンド引数・チャットへ書かない。既存鍵がある場合は、保存済み暗号文に対応する鍵を使用し、別鍵へ置換しない。

作業環境への環境変数設定に加え、Git外の0700親ディレクトリ/0600ファイルを明示する`--owner-key-file`にも対応する。symlink・公開権限・Git内のキーは拒否する。鍵をGitHubへ登録する機能や、既存secret値を読み出す機能はこのCLIに含めない。

```sh
python scripts/boat_pdca_github.py publish --state /private/pdca-state.sqlite --repo /path/to/RACE-AI --output /private/published-g1 --initialize
```

明示する場合だけ上記へ`--owner-key-file /private-owner-key/state-key.b64`を追加する。既存refを更新するときは`--initialize`の代わりに`--expected-parent PREVIOUS_ACCEPTED_COMMIT`を指定する。

出力`/private/published-g1/production-input.json`はcipher SHA/scope/immutable commit/pathだけを持つ。このメタデータを既存PRの`audit/state/boat-pdca-production-input.json`へ反映すると、既存`forecast-audit-ui.yml`内のproduction readback jobが固定commitの暗号文を1GETし、私的領域へ復元検証する。

```sh
python scripts/boat_pdca_github.py readback --input audit/state/boat-pdca-production-input.json --private-dir /private/production-readback
```

CIに渡す実データは暗号文のみ。復元したSQLite・原本・プロフィールは`RUNNER_TEMP`の私的領域に置き、artifactへ出すのは件数と受入状態だけ。ジョブには既存と同じ`contents:read`を使い、権限追加や新workflowを作らない。

## 現在の受入状態

既定入力は`WAITING_ENCRYPTED_INPUT`。鍵不足では`HOLD_OWNER_STATE_KEY_MISSING`、鍵があっても暗号文未公開なら`HOLD_ENCRYPTED_INPUT_REQUIRED`。どちらも源流GET0件で、成功した実データ同期とは扱わない。wrong key/hash/scope/pathや欠損状態は拒否し、旧版へfallbackしない。

継続確認のCI `42138375467` では、GitHub側の鍵検査が通り、PDCAの状態は`HOLD_ENCRYPTED_INPUT_REQUIRED`へ進んだ。ローカルの環境変数・秘密変数bindingは未設定であり、同じ既存鍵をこちらへ接続する必要がある。前runの鍵不足記録を、現在もGitHubに鍵がない証拠として使わない。

同CIで初めて実行された既存の全選手DB復元は失敗した。汎用codecのBase64正規表現が大きな暗号文でスタック上限を超えることを、架空8MiB入力で再現した。正規表現を外し、既存のサイズ上限・復号後の正規Base64再符号化一致・AES-GCM・scope検査を維持する修正と回帰テストを追加。大容量復元、違う鍵、不正/非正規/過大Base64、暗号文改変の拒否をローカルで確認した。実ファイルのGitHub再実行結果は別途確認し、暗号化ファイルの作成だけで復元成功を推定しない。

ローカルの実データjournalは156ペアを保持。既存workerの認証済み結果artifactを再利用し、2026-11-06 09:01 JST時点で締切済み3R中1Rを通常結果と照合、1Rは取得結果が未確定、1Rは未観測。各2モデルを別々に採点し、同じ結果を再実行しても結果版1・採点1のままだった。公式サイトへの追加取得は0件。

この1Rは観測相性の元版/履歴版とも的中、ST重視は元版的中/履歴版不的中。これはモデル別の1レース比較であり、全対象の的中率や改善効果の実証ではない。[原本や買い目を含まない件数証拠](evidence/2026-11-06/history-pdca-initial-real-result-counts.json)。予想は07:20 JST保存のV2をそのまま使用し、結果後に作り直していない。

ローカルの保存証拠とGitHub SHA一覧の存在確認を、正式forecast receiptへの接続完了と混同しない。`independent_pre_cutoff_receipt_verified=false`、`accuracy_improvement_proven=false`を維持する。実データの暗号化公開→別runner復元が完了するまでは、1〜4の全実運用完成とは報告しない。
