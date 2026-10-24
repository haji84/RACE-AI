# Codex parallel development runbook | RACE-AI 2026-10-25

**Required reading**: [3系統Master Handoff](CODEX_RACE_AI_THREE_STREAM_MASTER_HANDOFF_20261025.md), [Codex起動指示](CODEX_RACE_AI_START_PROMPT_20261025.md), Issue [#67](https://github.com/haji84/RACE-AI/issues/67), [#68](https://github.com/haji84/RACE-AI/issues/68).
**Instruction does NOT bypass the owner Human Gate, PR review, source licensing, costs or privacy.** CodeRabbit is excluded.

## 1. 完成責任型の開発手順（工程を省略しない）

**G0. GOAL & actual repository read**：Issue #67の製品Goalと全機能/非機能受入基準、53章PR #61との差分、共通工程・安全条件を再取得。GitHub main sha、PR #61/#64/#65/#69/#71/#72の現在のhead/base/draft、changed files、Actions exact-head CI、stacked依存をGitHub APIで採る。自分が記憶するSHAを現在HEADと断定しない。source rights・Publicリポジトリ・Cloudflare Access/D1/Quota の既存状態をREAD-ONLYから始める。

**G1. requirement classification**：機能を [P0 final Goal 必須] / [P1 品質/使いやすさ] / [P2 後回し可能] に分け、PR #61要件と採用Issue #67との差をSPEC_CONFLICTS.mdへ。既存成果を [CODE_IMPLEMENTED] / [SYNTHETIC_TESTED] / [REAL_SOURCE_OBSERVED] / [PROSPECTIVE_FROZEN] / [REAL_DEVICE_PASSED] / [INTEGRATED_MAIN] に分ける。未知は UNKNOWN。実際に見ないで「済」を書かない。新たな有益機能案は提案・採否記録を残し、根本GOALを勝手に変えない。

**G2. dependency-first architecture review**：共通全件RaceLedger、SourcePermission/Attribution & AsOf、SportEventTrigger、VersionedSnapShot、ExistingModelAdapter、AppendOnlyFreezeReceipt、OddsPostFreeze、OfficialSettlementRevision、PDCA、iPhone viewer、UsageBudgetのAPI/テーブル/所有レーンを定義。各変更前にBuilder以外の別AI09等で設計の機能抜け・競合・security・費用・前時点リーク・実機検証容易性を**批判的レビュー**。仕様や既存コードと不一致なら小規模P0 spikeで立証。不明は強行せずHOLD。

**G3. dynamic parallel execution**：安全な4つのlaneを下表に沿って運用。必要に応じ3本、4本、5本、1本に増減してよい。2本固定は不要。単に作業数を増やすのではなく、依存クリティカルパス・本物のテスト可否・競合解消コストでスケジュールする。独立レビュー/QAは実装担当から分離し、並列作業で起きる「同一枝への書込衝突」を防ぐ。実作業をCodexのサブタスクや隔離worktreeに割当てる。提供された権限外の複製PRや新たなrepoに勝手に展開しない。

**G4. bounded implementation**：担当は最初に元head + AllowedPaths + 成果確認方法をIssue #68へ報告。既存のPRに小さい差分として実装。新規モデルを作り直さない。依存関係が崩れたら自動で衝突回避のための新規PRを連発しない。大きい設計変更は独立設計レビューと必要なOwner Human Gate。権利が判明していないSourceに生GETループや永続保存を行わない。オッズ/人気/結果からモデルへのコード経路を負例で遮断。

**G5. test pyramid**：unit + property tests（欠測/出走数/日付・timezone・締切・F/L・同点・全組番）→古い回帰→該当統合者の独立fixture→GitHub Actions exact-head test→被許可の本物のソース実験→真の未来レース締切前E2E→Cloudflare Access/D1/iPhone Safari実機→回復・障害注入を分離。合成CI/旧実data/源流HTTP200は真のmodel E2Eではない。CI赤はレポートを保存し元の失敗条件を特定、**最小局所修正**。同じ方法を最大3回試し改善がなければ別原因を調査してreplan。セキュリティ検査を削って通してはならない。

**G6. independent review and fix**：別AI09、独立モデルまたは正当な別環境でsource/実装/仕様/テスト/CI/先行result/機密漏えい/モデルの未来リークを独立に点検。AIのレビュー結果はファイル・行・再現手順・HEAD SHA・テスト証拠で確認。実装担当が「レビュー済み」と自己申告するだけは禁止。CodeRabbit不使用。実GitHubの必要な正式APPROVEDは人間/適正GitHub認証の独立レビュアーが実施。INCONCLUSIVE、reviewer unavailable、head変更はDraft保留・再レビュー。

**G7. integrate smallest verified slice**：安全なPR順序/依存を確認。PR #69をいきなりmainへ置いてPR #71/#72をまとめてマージしない。共通API最小差分、既存PR間の正確なmerge-base/重複、race ledgerのmigration、rollbackをレビューしてOwner保護ルールに従う。main統合が許可されないときはDraftのまま残し、証拠と次の具体的なOwner GateをIssue #68へ。統合した場合もmain CIと実機を再試験。

**G8. acceptance and PDCA**：各Goal条件をtest-run-deploy-deviceの**本物の結果で**検証。全競技/対象レースの母数・未予想・凍結・公式結果の訂正・モデル間同一未来期間の成績と精度を別表に。所有者がiPhoneで認証/全120値/60秒3周期、モデル根拠画面を検収した場合にだけDEVICE_PASS。失敗を学習へ戻すが、事前固定した過去予想/モデル選択を改変しない。次のクリティカルP0を自動選択し、Owner Gateや製品完成まで無理に宣言しない。

**G9. restart recovery**：Issue #68やGitHubのread-only evidence ledgerに担当、前回head、成果物SHA、現在のblocked gate/最小操作、実run ID、次の優先タスクを保存。Codexが中断されたらまず現在GitHub shaを読み直して、同じheadなら再開、異なれば差分レビュー後に再計画。二重source GET、二重投稿、二重D1 revision、過去予想再凍結をidempotency keyで防ぐ。Actions schedule/GORIQ controllerの実運転がないのに「無人継続開発が稼働中」と書かない。

## 2. Dynamic parallel lanes and exclusive writer ownership

| lane | Work ownership (avoid touching other lane file paths) | Primary EXISTING PR | Parallel start condition | Mandatory output |
| --- | --- | --- | --- | --- |
| A: Source & pre-race | race_ai/*presentation*, official B/K; AUTORACE trial; JRA bodyweight; KEIRIN rider introduction; source rights/availability | PR #72 | shared race/source schema draft and scope identified | per-venue legitimate source plan; exact-race pre/post observation SHA and times; NO_FORECAST when missing |
| B: Odds + private display | workers/odds_*; web/full-odds.*; odds CLI/refresh; Cloudflare D1/owner-only UI contract | PR #71 | independent post-freeze odds firewall; rights/usage review | real odds120→private D1 SHA-readback→owner iPhone 60sec x3; quota/usage |
| C: existing prediction models | four_sport*models/suite/learning; boat_multi_feature_models/adapter; evidence model comparison, settlement | PR #71 + read PR #64 | input schema as-of and audit available | models unchanged vs new version separated; true future Top8 frozen external and result revision |
| D: Integration + QA + evidence | docs/asset reuse, spec conflicts, race ledger, security/CI, independent review, iPhone acceptance | PR #69 baseline; Issue #68 for orchestration | A/B/C path ownership established | same HEAD CI, review independent, branch/permission gates, integration readback |

**Critical concurrency**：PR #71 hosts both B and C. They may prepare patches in different isolated worktrees, but **do not simultaneously write to PR #71 branch** even on distinct files. Before any write use an exclusive scoped writer lock, query latest branch HEAD, require expected-HEAD CAS for mutation, update state on success, release lock. If the configured GitHub mutation does not allow compare-and-swap against branch HEAD, serialize via ONE integration writer and rerun the exact HEAD after each patch. Independent lane workers provide patches and tests to this integration writer; they do not race source-of-truth commits. PR #72 A changes likewise use exact-file SHA and branch-head freshness.

Never force push, rebase other agent's head, delete/overwrite unreviewed changes, disable branch protection or create dozens of duplicate PRs. If a necessary worktree/short-lived isolated branch is needed, that branch must remain controlled and be cleaned only after safe integration and recorded acceptance; **existing PR remains the authoritative PR**. External Cloudflare changes require an additional serialized Owner-only gate.

## 3. Concrete dependency DAG

Stage 0: read existing Issue/PRs + build asset reuse and source permission / cost matrix + exact HEAD ledger
→ Stage 1: common race/participant/time/rights schema & prediction/odds firewall (D)
→ Stage 2a (A): genuine legal data PENDING→AVAILABLE/partial for 3 sports + boat weather/K/form
→ Stage 2b (B): Cloudflare read-only state; owner auth/private iPhone; odds legal fetch + 3 x 60sec real source cycle (no prediction input)
→ Stage 2c (C): exact PR64/71 existing models fit incoming evidence, model reasons, no prior result leakage
→ Stage 3: authorized future 1R: real source snapshot → PR71 advanced models (separate baseline/shadow) → all trifectas → max8 → immutable independent external timestamp + hash readback before official cutoff
→ Stage 4: official results/payout/void/refund revision → Hit@8_all denominator + future A/B improvement
→ Stage 5: iPhone full 4 sport/evidence models acceptance & allowed all-races expansion
→ Stage 6: independent reviewer and applicable Human Gate → minimal PR integration/main readback/live proof → revisit unmet Goal.

**Parallel**: Stage 2a/2b/2c concurrently after Stage1; select number by actual dependency, platform limits and reviewer/CI throughput. Resume from completed evidence, do not repeat old unsuccessful source experiments without a changed hypothesis. Provide one concrete narrow task per lane with completion evidence.

## 4. Mandatory tests per lane

**Source lane A**: actual published vs generic web title; AUTORACE canceled banner false positive; racer/horse/vehicle ID; independent source first published vs first observed; PR64 K revision and ST F/L; same day output excluded; official provider license/allowed intervals; duplicate GET idempotency; expired/after-cutoff GET denial; not forcing rights from a public HTML page.

**Odds lane B**: 6 boats exactly 120 distinct triples; 7/9 competitors per sport with correct N*(N-1)*(N-2); odds not in forecast model features or model selection; protected access owner email NOT logged, unauthorized 401/403, expired Access rejected; private D1 size/row quotas; 60 sec x3 source capture + D1 and client with independent time; stale/source changed separately tracked; date boundary and cutoff; 429/backoff, cloud failure; no cost escalation; no raw third-party odds in Public GitHub; Worker deployed SHA vs PR71 source SHA; Safari evidence must be real.

**Model lane C**: same input snapshot SHA for all models; frozen predictions and hashes never updated; forbidden odds/popularity/result keys always rejected; historical sample_n and F/L not numeric zero; proper wind relative true bearing and true water/track conditions; no phantom source published timestamps; lane 6 first explanation must disclose real features; all valid triples; no >8 choices; revision and model version; synthetic baseline not official; official result changes do not mutate prediction.

**Integration D**: CI failed/re-run/recovery, SIGTERM/crash restart, idempotent running two parallel jobs, source revisional conflict, branch CAS lock, two lanes racing PR71, upstream 403/429, Cloudflare quota exhausted, iPhone owner access, official deadline revision; temporary review approval revoked after code changes; master Goal, security, paid/public choices stay Owner-controlled.

## 5. Human Gate & secrets

Explicit Owner approval REQUIRED for: top-level Goal changes, root architecture replacement, permanently dropping required features, license/right authorization not already established by independent evidence, high-frequency source crawling where provider conditions unknown, private source→public data disclosure, production public exposure and billing, Cloudflare plan/Access/RBAC/secret changes, destructive D1 migrations, deployment that changes others' budgets, auto-betting, weakening independent review/branch protection, forced push, main merge if not already covered by its formal policy.

Not an authorization by receiving this runbook. Unknown rights mean HOLD for THAT source/purpose, not entire research project. **Private credential values, owner identities, full 120-row odds, original videos/photos/HTML, unlicensed athlete-level records NEVER in public GitHub file, comments or workflow logs.**

## 6. Evidence classification and reporting

Every completion report must include: timestamp JST; exact main/PR head; changed paths; true CI URL; source right status; race/event date/venue/cutoff and data publication/observation times; input snapshot/PR model SHA; origin/capture/readback hash; accepted/denied features; official revision; iPhone URL authenticated/no screenshot secrets; BLOCKED items and next Owner question.

Status labels: PLANNED, CODE_WRITTEN, SYNTHETIC_CI_PASS, REAL_SOURCE_PARSE_PASS, SOURCE_RIGHTS_APPROVED, PRE_CUTOFF_MODEL_FROZEN, OFFICIAL_RESULT_MATCHED, IPHONE_REAL_DEVICE_PASS, INDEPENDENT_REVIEW_PASS, OFFICIAL_GITHUB_APPROVED, MAIN_INTEGRATED, PRODUCTION_VERIFIED. NEVER skip labels or promote one into another. Never assert 98% or finished all-races without prospective denominator evidence.

If in-session work cannot advance because of a missing tool/credential/account, finish all unrelated safe work and write **one precise owner action** and its expected proof into Issue #68. Do not promise future background execution absent a configured and actually observed automation.
