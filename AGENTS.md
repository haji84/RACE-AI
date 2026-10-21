# RACE AI development contract

The user's 2026-10-15 handover (chapters1–53) sets the product goal. main is the sole integrated code authority; Draft branches are proposals. Read PROJECT_STATE.md, ROADMAP.md and docs/RACE_AI_REQUIREMENTS_20261015.md, then refresh GitHub/Vercel before continuing. Snapshot state is evidence, not a live query.

Prioritize P0: protected Actions→Preview→private Blob proof, current JST feed, Tokuyama official reconciliation, responsive referenced UI. Independent lanes may proceed without starving P0. Ordinary investigation, branch changes, tests and Preview validation are authorized. Require user decision for new charges, destructive production changes, broad access changes and public release.

Never disable protection to pass a test; never put secrets in source, logs or URLs. Keep Preview/Production separated. No automatic betting or payments. Unknown source rights block only that purpose/source; do not invent grants or facts. Pictures/video remain separately scoped and private until allowed.

Use exact-head CI and independent reviewer evidence. Fix concrete failures, cap same-method failures at3. Record implementation, synthetic tests, live communications, real-source tests and actual iPhone Safari checks separately. A successful build or mocked test is not feature completion.

Persist code, requirements, blockers, run/deployment IDs and next actions in GitHub. Do not claim this Work session keeps running after it ends. Scheduled autonomous execution must exist and have observed executions before being reported active.

Do not merge the existing stacked Draft PRs wholesale. Confirm dependency order, latest head, differences, security and review. Public release remains a final user gate.


## Completion-first autonomous execution standard

For **every** RACE AI development task, optimize for verified product completion, not lines of code, number of PRs, or number of agent attempts.

- Define a stable, testable Done condition and the exact main revision being verified. A requirement is complete only with required implementation, tests, integration, independent review where applicable, and actual UI/runtime/real-data proof. Keep mock, CI, preview, real-device and production evidence distinct; never accept AI assertions as machine evidence.
- Prioritize the critical dependency path using explicit upstream blockers, downstream value, integration cost, testability and remaining work. Scores are scheduling heuristics, not guaranteed shortest time. Recompute the order when a blocker or dependency changes.
- Reuse proven existing code and integration branches first. Before creating any new PR, check duplicate work and stacked PR ancestry. Merge only after exact-head CI, review, branch protection, safety gates and applicable integration acceptance.
- Treat each task as implement → verify → review → integrate → actual outcome proof → update completion ledger. No code-only or PR-only Done. Reopen stale evidence when the implementation revision changes.
- On CI failure or conflicting PRs, record observed failure and diagnose, test an alternative within authorization, and replan after three identical failed method attempts. Preserve state for restart; test concurrency, failed CI and crash/restart with real evidence before calling unattended recovery implemented.
- Continue autonomous safe actions within granted scope, but never bypass Human Gates for public release, new costs, production/destructive actions, credentials, permissions, legal/source rights or security weakening.
- Introduce the execution controller first as a read-only pilot in PR #65. Its simulated fault-handling tests are not proof of production autonomous development. Require independent review and complete real workflow/real-machine verification before promoting this mechanism to the standard controller or copying it to other repositories.

Priority: preserve existing requirements, repo protections, safety authority, review independence and product scope. If a completion policy conflicts with an existing higher-authority security restriction, retain the restriction and report the conflict.

Reviewer policy (owner): Do NOT request, invoke, rely on, or count CodeRabbit as an independent reviewer. Use a separate authorized reviewer and inspect exact-head CI, code and security evidence. Bot-generated comments from CodeRabbit do not satisfy the review or merge gate.

## AI社員による独立レビュー（CodeRabbit不使用）

- CodeRabbitを依頼・起動・採用しない。過去のbotコメントやレビュー要約は完成条件、独立レビュー、PR承認の証拠に数えない。GitHub Appのインストール状態はこの文書だけで変更されない。
- 開発担当Builderとレビュー担当を分離する。QAが再現テストを担当し、GORIQのAI-09 Reviewerが最新PR head/base SHAの差分、実装、関連仕様、CI、セキュリティ・回帰リスクを読み取り専用で点検する。指摘時はDebugger/Builderへ根拠・ファイル・再現条件を引き渡す。
- 修正が入ればhead SHAを再照合し、AI-09が再審査。認証トークンはモデルに渡さず、PRコメント投稿は別の最小権限の検証済み投稿処理に分離する。AI-09の出力はAI_ASSERTEDの技術的助言でありGitHub APPROVEDではない。
- GORIQのAI-09自動投稿PR #1799は未統合、ZBook実機からコメントまでの自動E2Eも未実証。RACE AIのPR #65へ接続済みと扱わない。実機・権限・独立性・CI・GitHub側承認の証拠が揃うまでは統合Gateを保留する。
- 正式審査要件とHuman GateをAIの自己承認で置換しない。独立GitHubアカウント等のルールを省略・弱体化しない。

## 2026-10-21 4競技・クラウド実行の仕様追補

- 詳細差分の正本候補: `docs/RACE_AI_ACTIONS_CLOUD_DELTA_20261021.md`。Issue #67/#68を上位要件とする。**本変更はPR #61のDraft仕様でありmain/Productionの実装ではない**。
- ZBookを通常の収集・予想・結果照合・PDCAの必須依存にしない。既存GitHub Actions / Preview / private Blobを可能な限り再利用し、Cloudflareは未承認の比較候補とする。
- 4競技共通の日次台帳を構築し、オッズを参照する前に全有効3連単から最大8点を締切前に固定。オッズは**凍結後**の独立した購入価値判断のみ。旧仕様のodds/no-odds予測は今回の方針と衝突する限り使用しない。
- 定期ジョブの実行遅延/欠落、ZBook停止、外部取得失敗、時点リーク、再実行、永続復元の実E2Eを完了条件とする。Actionsの実行定義だけで無人運用完成と呼ばない。
- 機能要件の変更は独立レビュー/保護/権利/費用/一般公開のHuman Gateを緩めない。コード/モデル/クラウド移行は別の実行・受入工程で行う。

## 2026-10-21 最上位GOAL v1.1とCodex統合指示の参照

- 本PRの `docs/RACE_AI_98PCT_GOAL_AMENDMENT_20261021.md` は4競技・全発売評価可能レースでのオッズ非依存3連単最大8点・実測Hit@8_all 98%以上を**未達の研究目標**として規定する。保証・達成済み主張は禁止。
- ZBook非依存のActions運用詳細は `docs/RACE_AI_ACTIONS_CLOUD_DELTA_20261021.md`。**Codexへの統合実行指示**は `docs/CODEX_INTEGRATED_PRIORITY_20261021.md` に集約した。Issue #67/#68と矛盾があれば `SPEC_CONFLICTS.md` に記録し採否理由を残す。
- オッズ/人気/市場情報は学習・特徴量選択・モデル比較・推論・上位8点決定から隔離し、凍結後の経済評価に限定する。旧16/24/32点UIは別モードに隔離、公式AI精度の成績に混ぜない。未予想・見送り・締切超過を全発売評価可能レースの分母に残す。
- 既存53章詳細・PRの依存/正確なhead・SourcePermission・保護・独立レビュー・費用/公開Human Gateは維持。PR #61の提案内容であってmain/Productionへ採用済みとは扱わない。
