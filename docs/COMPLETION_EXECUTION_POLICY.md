# 完成優先型・自律開発Controller（RACE AI先行試験）

目的：PRやコードの増加ではなく、検証済み完成要件の増加と製品全体の完成を優先する。

## 非交渉ルール
1. 完成要件は、対象main SHAと一致する正式統合、要求されたunit/integration/runtime/独立review等の受入根拠が揃うまで未完成とする。AI自己申告は完成証拠にしない。
2. 要件の依存関係を検査し、残りの下流工程と優先度で順序を計算する。この採点は推定ヒューリスティックであり「数学的な最短期間」を保証しない。
3. 新規実装前に既存ブランチ、既存PR、重複と統合コストを確認する。別々のPRの乱立を避け、1つの機能は実装→CI→独立review→統合→実データ/実機検証までを完成単位とする。
4. CI失敗やPR競合は原因を記録し、同一原因・同一手法の失敗3回で別方式の再計画に切り替える。再起動で履歴を失わない。
5. セキュリティ、課金、公開、権限・資格情報、危険な本番変更など既存のHuman Gateを維持。必要な承認がない限り外部副作用のある処理を行わない。
6. 正本mainは保護し、実行エージェントは権限・Scope・既存AGENTS/仕様/PRレビューを迂回しない。安全でないときは失敗として記録する。

## 先行試験
- `node --test tests/completion-controller.test.mjs`：依存関係、CI失敗の再計画、PR競合、状態永続化と再開、古い/AI自己申告証拠の拒否。
- `node scripts/completion-controller.mjs --github --catalog config/completion-pilot.json`：GitHubを読み取り専用で監査（ネットワーク接続とAPI権限が必要）。PRを作成・統合・更新しない。
- `--snapshot <JSON>` により取得済み状態で再現可能な監査。
- `--state <JSON> --event <JSON>` により失敗履歴を原子的にローカル保存し、再起動後に復元する。

## 完成を主張してよい条件
この試験のカタログは製品53章の全要件を含まないため、製品完成率は計算・主張できない。`product_completion_claim_allowed=false`を維持する。
試験コードの単体テスト成功と、GitHubでの実際のCI/競合復旧・実機停止再開・自動マージ成功は別証拠。
自動で次Issueを作る、修正を実装する、権限内でPRを統合する、実機自動再開をする、といった外部書込みの自律化はこのPilotには未接続。
次は読み取りアダプターの実データ検証→現行開発Controllerへの接続→独立レビュー→権限内の段階的実動作検証。

共通化はRACE AI pilotの証拠を独立レビューしてから、既存のGORIQ/AIOS契約へ最小差分として行う。共通化前に全リポジトリを一括改変しない。

## 独立レビュー担当の制限
オーナー方針によりCodeRabbitは使用しない。自動コメントを含め同サービスの評価を独立レビュー完了の証拠として数えない。実装担当と独立した、明示的に許可された別レビュワーが最新head・差分・CI・安全性をレビューしなければ統合完了としない。

## AI社員レビュールート

実装・修正担当はBuilder/Debugger、試験担当はQA、技術的な独立レビュー担当はGORIQのAI社員AI-09 Reviewer。CodeRabbitは使用しない。以前のCodeRabbitへの依頼は誤りであり、その出力を独立レビューや完成の根拠に数えない。

受入前にPRの正確なbase/head SHA・差分・CI・仕様・既存レビューと未解決指摘を取得し、実装担当とは別のAI-09プロセスが指摘根拠を保存する。問題があればBuilder/Debuggerに渡し、修正後は新headに対して再評価する。QAは別途CIと実動作を確認する。

GORIQ mainにはAI-09の読み取り専用モデル評価機能（PR #1797）があるが、自動検出・GitHubコメント投稿をつなぐPR #1799は未統合で、実機の完走証拠も未達。GORIQ専用のコードがRACE AIのPRに対応済みとは見なさない。接続はローカル認証情報をモデルへ渡さない設計、最新head照合、別投稿主体、セキュリティ・権限・Human Gateを維持して別途審査する。

本PilotのRead-only判定だけで「AI社員レビュー完了」「GitHub APPROVED」「統合許可」を宣言してはならない。


## GORIQ AI-09 接続用の実装済み境界（PR #65）
- `scripts/ai09-review-handoff.mjs` はRACE AIのPR、最新base/head、対象commitのGitHub Actionsチェック結果を読み取り、`GORIQ_AI09_ADVISORY_REQUEST_V1` の機械可読リクエストを生成する。
- CIが最新SHAで揃わなければ `WAIT_FOR_EXACT_HEAD_CI`。揃った場合も `REQUEST_AI09` までで、モデルを起動したことにはならない。
- AI-09が問題を指摘した場合のBuilder/Debugger修正指示は、現段階では権限を持たない助言レコード。修正の実行・完了を示さない。古いhead/baseや第三者の単なるコメントは正式レビュー証拠として採用しない。
- `NO_ACTIONABLE_FINDINGS` でもGitHub正式承認、独立Reviewerアカウント、Human Gate、main統合の代替ではない。
- 本接続はGitHub read-only、PRからの任意コード実行なし、秘密情報をモデルへ送らず、書込み/merge/権限変更/公開はゼロ。
- GORIQ側PR #1799はCI成功済みだが、公開リポジトリ上のself-hosted ZBook隔離、当該正確なコミットの独立技術レビュー、workflowのissues:write有効化権限、実機Ollama→投稿のE2Eを満たすまで保留。RACE AIのレシート検証・限定権限のクロスリポジトリ投稿も未実装。
- 独立レビューはAI-09。CodeRabbitは呼び出さず、成果を採用しない。GORIQの既存AI社員体系を再利用し、第三者サービスへの置換はしない。

### 先行試験の実行方法
`node --test tests/ai09-review-handoff.test.mjs`（GitHub上のPRでは、既存completion-controller-pilotのテストと同時に実行）。
`node scripts/ai09-review-handoff.mjs --pr 65`（GitHub APIと読み取り権限が必要）。
出力が `REQUEST_AI09` でもレビュー済みではない。実機モデルが独立処理し、レビューレシートが検証できるまで完成として計上しない。
