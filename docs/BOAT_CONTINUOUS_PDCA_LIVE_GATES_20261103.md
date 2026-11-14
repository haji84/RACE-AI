# BOAT無人連続PDCA P0ゲート: 継続取得・実HTML解析・専用D1（2026-11-03 JST）

**完了判定: NO-GO for live unattended nationwide operation.** これは接続設定の許可を勝手に与える文書ではない。PR #71はDraft、main非統合、Production・課金・権限変更・自動投票なし。PR #64の未解決POST nonceの再利用・再送なし。

## 1. 一次情報とソース利用範囲

- [BOAT RACEオフィシャルサイトポリシー](https://www.boatrace.jp/owpc/pc/extra/policy.html)：権利を尊重し、サイト運営に支障のある大量送受信・大量アクセス等は禁止。個人研究用の低頻度参照と、全国24場を自動高頻度巡回して長期保存・学習・再配信する権利は同一ではない。
- [公式データダウンロード案内](https://www.boatrace.jp/owpc/pc/extra/data/download.html)：番組表・競走成績・レーサー期別成績のダウンロードを提供。日次/過去データは場ごとのHTML多数取得よりこの一括経路を優先し、配布形式・実際の利用条件・引用/帰属は別途審査する。
- [公式サービス・更新時刻](https://www.boatrace.jp/owpc/pc/extra/about.html)：日次情報の掲載開始は開催区分ごとに異なり、遅延あり、4:00〜4:30の閲覧停止時間がある。予想直前の展示/ST・当日結果・返還は日次配布とは別の採用条件を要する。
- 参考の第三者[艇愛ボートレースDB データ利用条件](https://boatrace-db.jp/about/data/)は**個人研究APIを許可し、取得は1日数回程度・出典表示・再配布不可**と説明。夜間更新の過去結果には利用候補だが、公式の当日リアルタイム展示・確定結果に置き換えず、必ず公式原本と照合。事前モデル入力へのオッズ混入禁止。

**判定:** 現在の公開情報から、Cloudflare Cronによる24場×12Rの公式HTML大量継続GET許諾は確認できない。`BOAT_RIGHTS_REVIEWED=false`のまま。日次バルクと許可された各レース速報の取得用途/上限を別に確認してから本番導入。

## 2. 実公式HTML 3層の一致試験

対象：2026-11-03 宮島4R `20261103-17-04`。PR #64固定Python公式解析器とPR #71のJavaScript解析器に、同じRAM内HTMLを渡し、**raw HTMLの保存/公開はゼロ**。予想生成・再計算・自動投票なし。

| One-shot run | 対象（公式取得回数） | Python | JavaScript | 独立した実結果 |
| --- | --- | --- | --- | --- |
| [41575787456](https://github.com/haji84/RACE-AI/actions/runs/41575787456) | racelist 1GET | PASS | FAIL `OFFICIAL_RACELIST_LANE_CHARS_1_65297` | 対象外 |
| [41575909745](https://github.com/haji84/RACE-AI/actions/runs/41575909745) | racelist 1GET | PASS | PASS（6艇ID/勝率/締切一致） | 対象外 |
| [41576152636](https://github.com/haji84/RACE-AI/actions/runs/41576152636) | racelist/beforeinfo/raceresult 3GET | 3層PASS | program PASS, exhibition PASS, result FAIL `OFFICIAL_RESULT_NONSTANDARD_FINISH` | 未認証 |
| [41576411272](https://github.com/haji84/RACE-AI/actions/runs/41576411272) | 同3層 3GET | 3層PASS | result FAIL `OFFICIAL_RESULT_ROSTER_MISMATCH` | 未認証 |
| [41576601208](https://github.com/haji84/RACE-AI/actions/runs/41576601208) | 同3層 3GET | 3層PASS | result FAIL `OFFICIAL_HTML_UNEXPECTED_TABLE` | 未認証 |

発見した原因と修正：全角数字U+FF11のNFKC正規化、下位着順の失格等を受理しながら上位3着・全6艇IDを厳密検証、着順なしの艇も照合IDへ含める。最後の失敗後、払戻・返還を本文テキストではなく`thead`から同定するよう修正、重複表の合成回帰テスト追加。

**注意:** 最終 `thead` 修正を入れた**後の同じ実HTMLでの結果パーサ一致は未検証**。合成CI合格を実結果解析PASSへ昇格しない。特殊結果（同着、返還、失格、転覆、取消、特払い）についても明示した分類ルールと別サンプルが必要。実解析が正しく確定できない結果はスコアにしない。

## 3. Cloudflare費用・専用リソースのRead-only監査

接続済みCloudflareアカウント内で確認できたD1は既存 `race-ai-odds-private-preview` のみ。Workersは `ai`, `goriq-verification-gate`, `race-ai-odds-private-preview`。**ボート専用 `race-ai-boat-private-pilot` は未作成**。既存D1・Workerへの勝手な機能混在はしない。

Cloudflare公式 ([Workersの上限](https://developers.cloudflare.com/workers/platform/limits/)、[D1料金/無料枠](https://developers.cloudflare.com/d1/platform/pricing/)) はWorkers Freeのリクエスト・Cron/CPUおよびD1行read/write・容量に**アカウント全体の枠**があると説明。無料枠内なら追加課金不要でも、アカウントが有料プランなら超過従量料金リスクがあるため、利用中プラン・既存アプリ消費量・請求上限を確認する必要がある。

2026-11-03 GitHub/Cloudflare連携で請求・利用情報をRead-only照会したが`/billable-usage/info`, `/billing/usage`, `/billing/spend-policies`はすべて**HTTP403（権限不足）**。費用0円・課金制限を確認できていないため、専用D1作成/Workerデプロイ/cron有効化は実施していない。

## 4. プログラム上の一巡と本番GO/NO-GO

PR #71には `boat_nonvercel_core.mjs` (事前凍結/改訂を追記・読戻し)、`boat_pdca_shadow.mjs` (過去の確定結果だけから次レース候補を別保存)、`boat_nonvercel_cron.mjs` (排他・結果照合/6h再確認・翌日監査)、`boat_nonvercel_schema.sql` (不変D1テーブル) を実装。Node/SQLiteの**合成データ**で結果→次レースシャドー保存の1巡は成功しているが、実D1での無人一巡成功ではない。

安全な移行順は以下：
1. 公式の日次バルクと当日展示の各情報源について目的別許可・上限確認。JS実HTML出走/展示/結果の一致確認と実失格・返還・訂正の正確な分類を完了。
2. 既存無料枠消費量とアカウントの請求上限を確認。認証非公開、他資源と分離した専用D1/Workerを**新規費用が生じないことが確定した場合のみ**作成し、`BOAT_AUTO_ENABLED=false`で別途権限テスト。
3. 1場の最新**未来**レースを、実展示→源流時点証拠→最大8点→締切前の外部保存/読戻し→公式結果/払戻→結果PDCA→後続レースの別モデル事前凍結まで、作成・受信時刻・SHAで無人実証。履歴予想の後付け禁止。
4. 1場12Rの取りこぼし・障害・再起動復旧・翌日訂正を検証し、正式KPIの分母に未予想/締切超過/見送りを残す。全国会場へ段階拡張。main・公開・有料資源・自動投票は別承認。

**評価状態:** `code_synthetic_e2e=PASS`, `real_racelist_js_parity=PASS_Miyajima4R`, `real_exhibition_js_parity=PASS_Miyajima4R`, `real_result_js_parity=BLOCKED`, `cloudflare_private_pilot_deployed=false`, `live_unattended_pdca=false`, `national_full_coverage=false`, `official_hit_at_8_all=null`.
