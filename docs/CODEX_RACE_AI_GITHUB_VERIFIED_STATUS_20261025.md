# RACE-AI Codex 並列開発・2026-10-25 最新GitHub照合台帳

> 目的： [3系統の統合引継ぎ](CODEX_RACE_AI_THREE_STREAM_MASTER_HANDOFF_20261025.md) と [並列runbook](CODEX_RACE_AI_PARALLEL_RUNBOOK_20261025.md) に、2026-10-25再確認したGitHubの**実際のhead/CI/依存**を結びつける。これは引継ぎの証拠であって、Codexセッションの起動・正式main統合・本番受入を意味しない。Codexは作業の冒頭にAPIで再fetchすること。

## 1. 正確に確認した正本の状態

| 対象 | GitHub APIによる確認結果 | 読み方 |
|---|---|---|
| [採用Goal Issue #67](https://github.com/haji84/RACE-AI/issues/67) | Open、4競技の全R前時点Top8/結果PDCA、実測Hit@8_allの挑戦的な98%目標 | 採用Goal優先。98%は未達・保証なし |
| [統合Issue #68](https://github.com/haji84/RACE-AI/issues/68) | Open、P0並列開発/再開正本 | Codexが工程・Owner Blockerを毎サイクル追記 |
| main | `8bb7d69f9c8fb302055bc9e2609903d1e8f73e4b`、保護あり | README中心。下記Draftを統合済みと書かない |
| [PR #61](https://github.com/haji84/RACE-AI/pull/61) | Draft `fef68607b4773c59d6d46aa04b9e9762a42683d4` → main | 53章/優先Goal/AGENTS/状態管理の仕様候補 |
| [PR #64](https://github.com/haji84/RACE-AI/pull/64) | Draft `761247bee0209e37b1af6b8885e92cad3e9260a5` → main、514ファイル | BOAT B/K/履歴/結果。巨大差分を無差別Mergeせず機能単位で再利用 |
| [PR #65](https://github.com/haji84/RACE-AI/pull/65) | Draft `989ffff1d6d2a3476dab41655038eda43f94fff7` → PR64 branch | 完成責任Controllerのread-only pilot、常駐ループではない |
| [PR #69](https://github.com/haji84/RACE-AI/pull/69) | Draft `bca59ebc5c7174e79d2dba027a97890f5d0d3d1f` → main | 4競技の共通合成E2E。PR71/72のstacked base |
| [PR #71](https://github.com/haji84/RACE-AI/pull/71) | Draft `a3d4d011fab8773e2eab07ca83580ab345dfb708` → PR69 branch | **同じbranchにオッズ/Cloudflare/iPhoneと高度モデルが同居**。CI [#40059352693](https://github.com/haji84/RACE-AI/actions/runs/40059352693)成功、合成中心 |
| [PR #72](https://github.com/haji84/RACE-AI/pull/72) | Draft `d15f41cacd3154b9e9d328da8d15baa9c903fba4` → PR69 branch | 展示/掲載/出典/権利/時刻・今回のCodex引継ぎ。CI [#40117503654](https://github.com/haji84/RACE-AI/actions/runs/40117503654)成功 |

**重要**：#71と#72は同じbaseを持つ別PRで、相互のコードが自動で見える構成ではない。現在のHEAD/差分/branch lockは上書き前に毎回再取得。**PR #71のB/C 2人が同時push禁止**。ほかのCodex実行が前進している可能性があるので、ここに記載したSHAを唯一の最新版と決めつけない。

## 2. 3系統＋統合（並列着手順を明記）

| レーンと主要既存PR | 並列に先行できるP0作業 | 合流前の証拠/受入 | 他レーンと衝突する箇所 |
|---|---|---|---|
| A 公式取得・展示/試走・情報公開 (#72) | 4競技の前日全R発見・公式`PENDING→AVAILABLE`を実レース前後2観測から証明するソース別adapter。source rights/published_at/captured_at/出走IDを保持し、欠測を0にしない。AUTORACEの「開催中止」定型文誤検知禁止、JRA CP932の馬体重欄と発表済の区別、KEIRIN日程と脚見せ/並びの区別 | 正当な提供元・日付/場/R・出走ID・公式公表/取得時刻・用途別利用条件、許容GET頻度。**実観測の出典SHA二時点の差分**（合成テストだけではNG） | PR64のB/Kをread-only再利用、共通Race/Source schema変更時はDと協議 |
| B オッズ/Cloudflare/iPhone (#71 odds paths) | 実装済み全3連単表示、公式BOAT120実値/D1 readbackの再利用。D1・Owner-only Access・配備Worker・日次Quota・アカウント共有無料枠をread-only照合。正式なソース条件のある**未来の1Rで**60秒×3回の真の取込/配信、iPhone Safariで本人ログイン・120/120閲覧の受入 | [既存Odds Handoff](https://github.com/haji84/RACE-AI/blob/feat/four-sport-forecast-audit-view-20261022/docs/HANDOFF_RACE_AI_20261024_LIVE_ODDS.md)。芦屋6/7・宮島3・平和島3は実120取得/D1 SHAに成功、Safari本人3周期は未確認。T-60とT-15/T-10の短縮案は**未決定** | Cと**同じPR71 branch**。Bはworkers/odds_*・web/full-odds.*、Cはrace_ai/モデル等を担当し、PR71へのwriter統合のみ1人に直列化 |
| C 高度予想・凍結・公式結果PDCA (#71 model paths、PR64読取) | PR71の総合要因/シナリオ/条件付き対戦/着順展開モデルをそのまま利用。K/展示/試走/ライン/馬体/風向の許可済み前時点スナップショット、`sample_n`とmissing reason、価格情報遮断をテスト。合法な実未来1Rで全有効組番評価→各モデル最大8点→外部独立時刻付きappend-only保存→公式結果・改訂/返還照合。B-LITEは比較用だけ | PR71既存 `four_sport_model_suite.py` / `boat_multi_feature_models.py` 等のモデルID・係数不変更。SHA/用途許諾/取得時点が欠ければNO_FORECAST。合成入力を正式Hit@8に数えない | Aの実データcontract待ち、PR71 writerはBと排他、Dが予想入力/市場のAPI firewallを監査 |
| D 統合/独立QA/Goal（Issue #68、PR69 baseline） | RaceLedger全件と締切順/出走revision/未予想理由、同一`race_id`のSource→Prediction→FrozenReceipt→Results→PDCA→Safari表示を一つの追跡鎖に統一。並列のAllowedPaths・base SHA・CI/レビュー結果を公開Issueへ保存。独立AI09と正当なGitHub reviewerはBuilderと分離 | すべてのP0を履歴付きGoal Ledgerへ。独立モデル批判レビュー・正式認証のAPPROVEDを混同しない。main統合は正式レビュー/Owner Gateを通るまではDraft | PR69のstacked base、A/B/C共有contractとmigration、Cloudflare private配信 |

**最初のparallel launch**：D が共有 `RaceID/Participant/SourceEvidence/AsOf/Permission/ModelFreeze/ResultRevision` とmarket firewallを確認 → A/B/Cを独立worktreeへ発行。AはPR72既存path、BとCはPR71内で**別worktree・別OwnedPaths**だが push権限は「単一integrator」へ集約。レビュー担当は別実行環境/別モデルを利用。フラグ一括変更・大規模スケジュール起動はしない。工程を「設計→レビュー→実装→CI→独立レビュー→修正→実実証→安全な統合→次作業」に固定し、詰まったときはその作業をBLOCKEDとして他を継続する。

## 3. 開発の最短クリティカルパスとゴールを偽らない分類

1. **M0** 既存PR read-only照合：実装済/合成テスト/実元ソース/Source rights/Cloudflare配備済を分類し、`ASSET_REUSE_MATRIX`と`SPEC_CONFLICTS`をHEAD付き更新。特にオッズ更新を展示トリガーと混同しない。
2. **M1** データ・権利・時刻契約：各sportの未許諾ソースを用途単位でBLOCK。元レースのK/ST/F/L/結果、公式販売締切、初掲載と初観測を分離。全組番・結果revisionの不変性/価格→モデルへの逆流拒否を機械テスト。
3. **M2** A/B/C並列実装：既存PRを修正し、同一部分の新規PRは作らない。CI exact HEAD → 独立AI09 → evidence reviewを繰り返す。**設計・合成CIと実際の自動運用は別**。
4. **M3** 許可済み**未来の実レース1R**：正式な`race_id`とcutoff、公式掲載トリガー、必要な前時点データ → 既存PR71の総合/展開等を実行、全組番から各最大8点 → 外部受付/署名/読戻しを締切前に確認 → 確定結果/返還/改訂を別時点で照合。同一レースで予想/オッズの時刻契約を混ぜない。
5. **M4** 将来の全R：すべての4競技発売/evaluableレースを台帳化し、見送り/締切超過/未予想を正式分母から消さずHit@8_allを検証。98%は前向き実測で成立しない限り**未達**。Owner-only Safariと無料枠超過ゼロ/復旧も実機試験。
6. **M5** 独立レビュー・正式GitHub認証承認・許されたmain統合と本番同一版readback。その後も実際の全件カバレッジ・連続運転が示されるまで完成宣言なし。

## 4. Owner Human Gates（このファイルでは包括承認しない）

- 課金/Cloudflareプラン変更・権限/Access/Secrets/RBACの変更・他アプリの共有無料枠に影響する高頻度処理
- 契約未確認の大量/反復ソースGET、公式HTML/動画/音声/馬体重/選手別データの継続保存/学習/第三者公開
- D1の破壊的migration、Prod/インターネット一般公開、main合流/branch保護解除/独立Reviewerの変更
- 自動投票/決済、上位GOAL/根幹アーキテクチャの改定、過去予想のfreeze変更や結果後のモデル重み改変

**Owner操作が必要なとき**：GitHub [Issue #68](https://github.com/haji84/RACE-AI/issues/68)へ「その操作1件・理由・承認対象・料金・権利根拠・できる最小の代替・現在の成功HEAD/CI・再開コマンド」を先回りして記録。技術作業の別レーンを止めない。正式な第三者承認が不可能な状態で「完成」や「承認済み」は書かない。

## 5. そのまま送るCodex起動指示の保管場所

**[CODEX_RACE_AI_START_PROMPT_20261025.md](CODEX_RACE_AI_START_PROMPT_20261025.md)** の「Codexに送る指示文（全文）」を、RACE-AI GitHubを操作できるCodexへ渡す。実作業をこのチャットだけで未来まで無人実行するという宣言ではない。

状況更新のたびに `docs/CODEX_RACE_AI_THREE_STREAM_MASTER_HANDOFF_20261025.md`、`docs/CODEX_RACE_AI_PARALLEL_RUNBOOK_20261025.md` と Issue #68 の証拠を合わせて読む。main/PR71/PR72のHEADを**上の確認値で固定せず再fetch**。
