# RACE-AI ボート展示後予想 非Vercel運用ゲート（2026-11-03）

## 実測で完了した部分

- 既存Draft PR #71で、`workers/boat_nonvercel_core.mjs`、`workers/boat_nonvercel_schema.sql`、`workers/boat_nonvercel_cron.mjs`、`workers/boat_official_html.mjs`とテストを開発。既存PR #64は変更していない。
- `workers/boat_nonvercel.wrangler.jsonc.example`は**disabled**・`workers_dev:false`・**cron未設定**の隔離運用サンプル。データベースID未設定のため、そのまま実運用できない。
- 本物の2026-11-03宮島1Rの**公式racelist+beforeinfo**をGitHub Actionsから取得し、PR64固定版のPython parserで6艇と締切を検証。上位8点を事前生成、GitHub Actions artifact `13193749273`に**10:03:09 JST**保存（10:18予定締切の891秒前）。別証拠: [実行](https://github.com/haji84/RACE-AI/actions/runs/41557112331)、[証拠記録](docs/evidence/2026-11-03/boat-miyajima1r-real-freeze-proof.md)。
- この保存先はGitHub Actions artifact。非公開D1への保存やCloudflare Workerの実稼働を証明するものではない。artifactは7日保持で、非公開長期固定台帳ではない。実際のモデル的中確率は**未校正**。

## 発見した阻害要因

1. **JS公開ページパーサ**: PR64 Python parserは実データ取得に成功。一方Cloudflare側`boat_official_html.mjs`の再現試験は、公式ページに別日リンク、1艇につき4表示行（6艇で24行）がある点で段階的に停止した。実修正は導入したが、修正後の別実例では`OFFICIAL_RACELIST_LANE_INVALID`が出ており、**同一実HTMLでの6艇完全一致はまだ0件**。この状態で実Cronを有効化しない。生HTMLは保存・再公開せず、修正時はRAM内でPython/JSを比較する。
2. **Cloudflare Preview/D1**: 接続先アカウントには既存`race-ai-odds-private-preview` Worker/D1があるが、これは別用途。二重開発と既存データ破損を避けるため勝手に変更しない。独立したD1作成、privateバインディング、Cron設置は未実施。料金プランの正式検証に必要なBilling APIは403（scope不足）、**追加請求0円と断言できない**。
3. **結果照合**: コードは本物の公式結果表6艇・払戻・返還なしを要求し、結果訂正は別追記。Cloudflare DBでの実結果→PDCA→新レース自動更新は未実証。
4. **配信**: 現在のWorkerはHTTPへ404しか返さない設計。iPhone配信/通知は未実装。公開経路とアクセス制御は別承認で設計。

## 以後の具体的実装・受入順

1. **ブロッカーをつぶす**: 同一公式HTMLをRAM内でPR64 PythonとJS解析して6艇/6タイム/予定締切/国別率を一致させる。実HTMLの断片を保存しない場合でも、検査結果の項目ハッシュと状態を記録。HTML構造変更・他日リンク・展示未公開・欠場・返還の安全停止テストをCIへ追加。
2. **プレビュー隔離**: 専用D1作成（既存D1に無断でテーブルを混在させない）、append-only schema適用、private Workerバインディングを確認。課金/権限/本番公開の可能性がある変更はオーナー承認の範囲内だけ行う。
3. **実1件E2E**: 本物の翌開催/新しい未締切レースで、`scheduled`→公式データ取得→PL研究予想→DB INSERT ONLY→D1 readback + db_stored_at締切前→公式確定結果照合→結果revision保存まで、実run/分単位時刻/監査ハッシュを確認。
4. **連続実行**: 上記の後にCloudflare `* * * * *` Cronを有効化、最低1会場全12Rを対象に未予想・漏れ・障害から復旧を実測。レースごとの再実行は同一固定予想を変えず、結果から改善候補を別モデルへ。見送りと未保存も分母に加える。
5. **全会場/スマホ**: 1会場の実完走後に24場へ広げ、許諾と費用予算を再評価。新しい公開・配信認証・課金・自動投票は別承認。

**Doneの判定**: 今の時点では「実公式展示の1レース締切前GitHub artifact保存」までのみ合格。「Cloudflareの実レースD1凍結」「結果自動PDCA」「全レース無人継続」は未達。CI成功を実運用成功と呼ばない。
