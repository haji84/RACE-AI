# RACE-AI 次チャット正式引き継ぎ書（2026-10-24 JST）

> **次のチャットは、必ずこのファイルを先に読んでから、GitHub/Cloudflareの最新実状態を再確認して再開すること。**
>
> 対象：4競技全レース予想・全3連単オッズ・締切前公開・PDCAのうち、P0「**実オッズ1レース全120組番 → Cloudflare D1 → iPhone画面60秒受信**」。
>
> この引き継ぎ書は **2026-10-24 11:57 JST以降に照合した記録**に基づく。過去の成功を未完と誤解したり、合成テストを実レース達成と報告したりしない。

## 1. 正本・ブランチ・引き継ぎ入口

| 項目 | 正本 |
|---|---|
| Repository | https://github.com/haji84/RACE-AI |
| 最上位Goal/進捗 | [Issue #67](https://github.com/haji84/RACE-AI/issues/67) |
| 継続開発管理 | [Issue #68](https://github.com/haji84/RACE-AI/issues/68) |
| 今回のオッズ・画面・クラウド実装 | [Draft PR #71](https://github.com/haji84/RACE-AI/pull/71) |
| PR #71 の **作業ブランチ** | `feat/four-sport-forecast-audit-view-20261022` |
| PR #71 の **base** | `codex/actions-four-sport-e2e`（**mainではない**） |
| 原本B/LZHなど既存研究資産 | [Draft PR #64](https://github.com/haji84/RACE-AI/pull/64)（`codex/race-ai-completion` → main） |
| 4競技共通の先行基盤 | [Draft PR #69](https://github.com/haji84/RACE-AI/pull/69)（`codex/actions-four-sport-e2e` → main） |
| ソース/権利の別途監査 | [Draft PR #72](https://github.com/haji84/RACE-AI/pull/72) |
| この引き継ぎ作成前に確認した PR #71 HEAD | `0eb232ff2185c76ae1eaaf3c46427774027d541c`（**この文書追加後のheadは変わる**） |
| 最新確認済みCI | [Actions #40055786751](https://github.com/haji84/RACE-AI/actions/runs/40055786751) completed/success（上記headの時点） |

**重要**：並行開発の可能性がある。次チャットではPRのhead、既存差分、Draft状態、CI、main/先行PRの状態を**必ず最初に再取得**する。PRを乱立させず、既存PR #71を優先再利用。Draftのまま保護し、main統合は独立レビュー・承認ゲートとE2E証拠を満たしてから。

## 2. 正式製品GOAL（変更禁止）

1. **ボートレース・競輪・オートレース・競馬**の全対象日次レースを見つけて、出走情報・条件・過去実績・展開を解析。欠測や未取得レースも台帳から落とさない。
2. 各レースの**最大8点の3連単**を、能力/直近状態/コース/ライン/展示・気象・レース展開などの正当に利用可能な**予想時点情報だけ**から選ぶ。人気・オッズ・確定結果は買い目選択や重み変更に使わない。
3. 公式の**販売締切T**を基準に、初回予想公開目標T-30分、購入を検討できる**正式8点のユーザー公開・独立時刻レシート完了目標T-10分**。内部生成だけ、T直前の形式的凍結だけは完成とみなさない。凍結後の8点の書き換え、過去のモデル実績の後付け改善は禁止。
4. AI8点の内外に関係なく、**全有効3連単組番のオッズ**をiPhoneで表示。組番検索・1着固定・ソート・想定払戻・最新性警告。オッズ表示はモデル/Top8保存とは分離。
5. オッズは、正当な取得条件を守りながら、原則**締切前60分に入ったレースで60秒間隔の取得・配信**を目指す。毎分画面確認 ≠ 提供元の実価格が毎分変化、を明示。
6. 重いAI推論・学習・日次PDCAは主として**GitHub Actions**。Cloudflareは軽い取得制御、同一ソースの共有、認証、最新オッズの保存・読出し。ZBookを常時起動しない。
7. **0円追加コストを基本方針**とするが、無料枠の収容力が測れていないのに無料を保証しない。無料枠の不足/提供元の権利未確定による欠測は正直に記録し、機能削除・偽データ・無断課金で埋めない。
8. 公式結果と改訂履歴により**事前固定された予想だけ**で実Hit@8・回収率・モデル差分を測り、将来レースでPDCA。目標98%は高い志向値であり達成済み・保証可能な数値ではない。自動購入/投票は対象外。

## 3. 2026-10-24に本当に達成した公式実オッズE2Eの一部

このセクションは合成値ではなく、公式BOATRACE `odds3t` レース別ページに対し、Cloudflare Browser Runの**小規模な手動単発ページ取得**から得た独立した実測の記録。

| 当日実レース | 公式締切予定 | 公式3連単実取得と観測 | 証拠 |
|---|---|---|---|
| **芦屋7R** `20261024-21-07` | **11:35 JST** | **10:40:01 / 10:41:57 / 10:43:21**、各120/120、公式オッズ更新時刻 **10:36のまま**、値変化0、最新D1を不要な重複更新せず | [原本SHA/3回の取得証拠](evidence/2026-10-24-boatrace-ashiya-7r-real-odds-pilot.md) |
| **芦屋6R** `20261024-21-06` | **11:05 JST** | **10:58:36（T-6:23）→11:00:28（T-4:31）**、120/120、公式更新 **10:57→10:59**。照合可能な8組番**8/8変化**。初回120全値は保存しなかったため全120変化数は主張しない。2回目120をD1に保存、SHA読戻しPASS | [締切10分以内実証](evidence/2026-10-24-boatrace-ashiya-6r-ten-minute-odds-pilot.md) |
| **宮島3R** `20261024-17-03` | **11:15 JST** | 正規D1基準 **11:09:42→11:11:09**、120/120、公式更新 **11:09→11:11**、**全120/120組番の値が変化**、保存SHAを各回照合PASS。保存完了間隔**86.834秒** | [締切10分以内実証](evidence/2026-10-24-miyajima-3r-under-10min-odds-pilot.md) |
| **平和島3R** `20261024-04-03` | **11:48 JST** | **11:44:23（T-約4分）→11:46:05（T-約2分）**、120/120、公式更新**11:43→11:45**、**118/120組番（98.3%）の値変化**。2回の公式値をD1へ異なるSHAで保存し読戻しPASS。完了間隔**101.193秒** | [最終10分での変化の正本](evidence/2026-10-24-heiwajima-3r-final-ten-minute-odds-changes.md) |

**結論：前チャット依頼の「締切10分以内の実レースで変化するか検証」は、すでに複数レースでPASSした。** 次チャットで同じ10月24日の締切済レースに意味のない追加リクエストを繰り返さないこと。必要なら**未来の開催日・未締切レース**を選び、許容負荷と権利範囲の中で次の未達ゲートを検証する。

### 値が変わらなかった理由を断定しない

芦屋7Rでは締切まで遠く、公式更新時刻が10:36で停止した同値観測。芦屋6R/宮島3R/平和島3Rでは締切10分以内に変化した。ただし、**展示が完了したから変動した**という因果を認定するには、展示完了の正確な公表時刻と前後の同一レースオッズを別途記録する必要がある。現時点で未立証。公開元の厳密60秒更新頻度も未証明。

## 4. Cloudflareの実機リソースと現状（2026-10-24のAPI読戻し）

**接続先は既存のCloudflareアカウント。秘密鍵・メール・Access JWT・APIトークンはこの文書や公開GitHubに記載しない。**

| 項目 | 実在する環境・状態 |
|---|---|
| D1 | `race-ai-odds-private-preview`（APAC、専用） |
| 最新実オッズ | D1 `odds_latest` に**4レース**：芦屋6R/7R、宮島3R、平和島3R。それぞれ全120組番のJSONを1レース1行で保持 |
| 取得監査 | `odds_pilot_measurements`に **芦屋7R=3、芦屋6R=1、宮島3R=2、平和島3R=2** の計8件の取得時刻/公式更新時刻/件数/SHAが存在。試験中の最初の読み取りで保存しなかったケースはここに含まれない |
| 試験上限 | `odds_ingest_quota` 2026-10-24 UTC **6回使用**、芦屋6R固有 `odds_pilot_race_quota` **2/3**。別に平和島3Rの `odds_short_window_trial` は**3/3**（失敗を含む、正式資料の記述）。次チャットでレース固有上限をリセットしたり同日再取得を強行しない |
| Worker | `race-ai-odds-private-preview`、`workers.dev`の専用保護URL。バインド先D1も確認 |
| Cloudflare Access | `RACE-AI Odds Preview - Owner only`。所有者メール1件のAllow、Worker内部も`ctx.access.getIdentity()`一致を必須 |
| Worker設定 | `ODDS_REQUIRE_ACCESS=true`、`ODDS_PREVIEW_READ_ENABLED=true`、**`ODDS_PREVIEW_INGEST_ENABLED=false`**。`ODDS_PILOT_RACE_ID=20261024-21-07`、`ODDS_PILOT_MAX_UPDATES_PER_DAY=3`（手動先行試験時の値）。**無人ソースCron無し** |
| 主なDB表 | `odds_latest`、`odds_pilot_measurements`、`odds_ingest_quota`、`odds_pilot_race_quota`、`odds_pilot_capture_failures`ほか。クラウドに新規DDLを適用する場合は先にschema introspection・既存値退避と非破壊レビュー |
| 実機表示 | iPhone Safariでの所有者Accessログイン/全120件表示と、実際の60秒ごとのUI受信証拠**未受入** |
| WorkerとGitHub | **GitHub PR #71の最新コードとCloudflare配備済みWorkerが同一SHAとは限らない**。特に新しい容量ガード/更新上限/画面は配布差分照合が必要。勝手に全機能を本番反映しない |

### 所有者専用閲覧URL

- [平和島3R・最新公式オッズ120件の保護画面](https://race-ai-odds-private-preview.qq-1130034.workers.dev/full-odds.html?race_id=20261024-04-03)
- [宮島3R・保護画面](https://race-ai-odds-private-preview.qq-1130034.workers.dev/full-odds.html?race_id=20261024-17-03)
- [芦屋6R・保護画面](https://race-ai-odds-private-preview.qq-1130034.workers.dev/full-odds.html?race_id=20261024-21-06)
- [Cloudflare private /health](https://race-ai-odds-private-preview.qq-1130034.workers.dev/health)

すべて終了した過去のレースなので、画面は「**締切後の参考値**」と表示すべき。URLの存在やD1成功だけで、ユーザーがiPhoneで画面を見たと主張しない。未ログイン検証ではCloudflare Accessに誘導され、実JSONの一般公開はされなかった。

## 5. 重要な障害と費用の制約

### 取得先/Browser Run

- 正式な公開データの閲覧は可能だが、公開されていることと、**全4競技/全国全レースの毎分自動取得・保存・再公開の許諾は別**。機械取得権利・キャッシュ条件・主催者/API規約・著作権法の適用除外・提供元の実更新頻度を独立に確認する。
- 2026-10-24芦屋6Rでの展示ページ追加調査が**Cloudflare Browser Run API 429 / 2001**で失敗。これは**Cloudflare側の制限**であり、BOATRACE発行の429と混同しない。
- 平和島3Rの3回目は**Cloudflare Browser Run API HTTP422 / code6002（タイムアウト）**。失敗をD1 `odds_pilot_capture_failures`へ記録。リトライ連打や有料化を自動で行わない。
- Browser Runの毎分・全国取得は通信/実行時間に対して無料枠とサービス制限が現実的に厳しい可能性がある。**最初の実証で価値を確認できた一方、Browser Runスクレイピングをそのまま全R毎分本番方式と決定しない**。権利/原本形式/費用を確認した正規データ提供経路の検討を続ける。

### Cloudflare無料枠

- Workers Free：**10万Worker requests/日**、CPU上限（Cloudflare公式現行条件参照）。
- D1 Free：**500万読取行/日、10万書込行/日、容量5GB**。索引更新、取得監査/Quota表の行も使用量に含める。
- [無料枠自動見積コード](../race_ai/free_tier_budget.py) と [容量仕様](P0_CLOUDFLARE_FREE_TIER_BUDGET_20261024.md) は、他サービス分の使用量が確認できない場合はHOLD。安全設計上は全体無料枠の**60%を自主上限の目安**とする。
- 300R × 締切前60分毎分オッズ = 約**18,000 upstream取得/日**。D1は最新値、索引、Quota台帳込み概算**54,000書込行/日**。実際のSQLコスト・Browser Run実行時間・ユーザー側API通信・他アプリ消費量は要実測。
- **Cloudflare Billing Usage APIはOAuth権限不足でHTTP403**のため、GORIQ等を含めた本当のアカウント残額/日次枠は未確認。空欄を0とみなさない。Cloudflare Dashboardで各機能のUsage/Metricsを確認し、可能な限り接続APIでread-only観測する。
- 予想学習/再計算をCloudflareへ移さず**GitHub Actions中心**。Cloudflare PagesでHTML/CSS/JSだけを静的に配信できる場合、Worker API通信を削減する。**Worker cache hitはWorker request数自体の削減にはならない**ので効果を誇張しない。
- Cloudflare既存プラン変更・有料契約・全サービス公開・main merge・権限緩和は**必ず所有者事前承認**。

## 6. 既存コード資産を使い、新たなモデルやPRを増やさない

| 用途 | 正本 |
|---|---|
| 実BOATRACE3連単HTMLのオフライン変換契約 | [`race_ai/boat_official_3t_odds_adapter.py`](../race_ai/boat_official_3t_odds_adapter.py) |
| 権利ゲート付き私的JSON変換 | [`race_ai/boat_3t_odds_handoff_cli.py`](../race_ai/boat_3t_odds_handoff_cli.py)、[`race_ai/permissioned_source_delivery.py`](../race_ai/permissioned_source_delivery.py) |
| 締切順・上流通信なしの毎分取得計画 | [`race_ai/odds_refresh_plan.py`](../race_ai/odds_refresh_plan.py)（T-60既定だが source GET実行は別） |
| Cloudflare D1/owner-only Access/配信 | [`workers/odds_feed_worker.mjs`](../workers/odds_feed_worker.mjs)、[`workers/odds_schema.sql`](../workers/odds_schema.sql) |
| iPhone全3連単組番表示（サイト内60s読戻） | [`web/full-odds.html`](../web/full-odds.html)、`web/full-odds.js`、`web/full-odds-model.js` |
| Owner-only Worker組込UI | [`workers/odds_preview_assets.mjs`](../workers/odds_preview_assets.mjs) |
| 容量見積 | [`race_ai/free_tier_budget.py`](../race_ai/free_tier_budget.py) |
| 予想公開T-10の時刻契約 | [`race_ai/purchase_window_policy.py`](../race_ai/purchase_window_policy.py) |
| PythonとNode/Worker contract | `tests/test_boat_official_3t_odds_adapter.py`、`tests/test_odds_refresh_plan.py`、`tests/test_free_tier_budget.py`、`tests/odds_feed_worker.test.mjs`ほか |
| 現行画面・公開期限の正式仕様 | [`docs/PURCHASE_BUFFER_AND_FULL_ODDS_V1_20261023.md`](PURCHASE_BUFFER_AND_FULL_ODDS_V1_20261023.md) |
| 実原本からE2Eの受入ゲート | [`docs/ODDS_REAL_SOURCE_E2E_GATE_20261023.md`](ODDS_REAL_SOURCE_E2E_GATE_20261023.md) |

**CI注記**：GitHub Actions `.github/workflows/forecast-audit-ui.yml`の既存テストと現行 head を確認。先行PR #64は巨大で別Draft。依存統合・既存PRの巻き戻りや衝突を把握してから安全に修正。今回の実計測で使ったCloudflare Browser Run抽出は、独立したCloudflare APIの単発実行で、**無人本番取得ジョブではない**。研究実測した最新値と正式ユーザー公開予想・凍結原本の区別を厳守する。

## 7. 次のチャットで実施するP0作業（安全な順序）

1. **正本再照合**。PR #71 head・base・Draft・CI、Issue #67最新コメントと本引き継ぎを読み、Cloudflare（`odds_latest`の4R・Access・Owner-only Worker ingest=false・既存quota/429履歴）をread-only確認。過去の7R/6R/宮島/平和島の同日試験を再実行しない。
2. **iPhone Safari受入**。最初はowner-only平和島3R等の**過去レース**の全120組番が表示されるか、認証が成功するか、表示時刻と60秒更新時の**実際の画面再読込結果**をユーザー実機で確認。機密認証情報や第三者の転載可否未確認の全オッズ数値を公開貼付しない。表示失敗ならSource/Worker/Safariのどこで失敗したかを特定。必要ならread-only診断を先に作る。
3. **自動60秒の独立実証**。許容される形式・用途・頻度が検証された**次の未来の1レース**を対象に、最低3周期を独立に時刻証明。source publish→get開始/完了→D1受信/読戻→iPhone到達の全時間を記録。公式の更新が変わらなくても失敗と決めつけず、同値/遅延を分ける。単発の手動2スナップショットを60秒Cron実証へすり替えない。
4. **取得元の公式性とコスト**。現在Cloudflare Browser Runには実429/タイムアウトが出ている。従って最小1Rの合法な取得方式/原本アクセス・保持/派生表示の権限・通信負荷、無料枠残量を調べ直し、低コストで実際に60秒を満たすかE2E測定。403/429が出たら即バックオフしてサイト負荷/費用を増やさない。
5. **データ品質**。全120券の組番→値が正しいか、取消/発売停止/締切変更への対応、`source_published_at` とWorker`received_at`の差、同じレースの別版・SHA・取得欠損と訂正を検証。JSONを1レース1行にし、変化しない価格の不要な全面上書きは避ける。監査証拠は転載制限を守りハッシュ・時刻・少数例・差分数中心。
6. **最終Goalへ展開**。容量と利用条件の実測ゲートを通過後だけ、4競技/全レースへ順次広げる。同時に予想側の独立T-10公開レシート、公式結果/払戻照合、将来予想だけのPDCAを進める。98%達成等の根拠なき実績表示は禁止。

### 「完了した」と言ってよい条件

最低1つの未来開催レースで、**合法な公式全120オッズ原本→複数回の認証可能な60秒間隔の自動取得→非公開D1保存/独立SHA読戻→iPhone Safari所有者画面に全120件＋提供時刻/受信時刻が更新された証拠**が揃ったときに限り「単一レース全120オッズ60秒配信E2E PASS」とする。正しい公式時刻で値が同じ場合は「取得は成功、公式値不変」と区別する。

その後の「4競技全レース完成」は**別の受入ゲート**。全Rの取りこぼし、提供元の更新時間、アカウント総費用、iPhone実機、独立レビュー、モデルの真正な事前固定、結果照合が揃って初めて判定。部分的なCI成功やCloudflare構成の存在で完成宣言しない。

## 8. 統治・操作禁止事項

- Source再配布権限を根拠なく拡張しない。公表値に対する合法的な情報解析の余地と、サイト上流の大量アクセス/契約規約は別ゲート。
- **秘密鍵、Cloudflareの所有者メール、API token/Access JWT、実レースの全120オッズ原文は公開GitHubに記載しない**。
- PR #71はDraft・main未統合。ユーザーの独立レビュー規則・承認ゲートを飛ばさず、CI失敗なら原因を局所修正し、未完の原PRを使う。
- オッズを予想モデル/正式8点の採否へ渡さない。最終販売締切、ユーザー閲覧時刻、独立外部凍結、モデル版と結果の時刻を混同しない。
- 新規有料契約、Cloudflareの料金プラン変更、本番一般公開、大規模全国Cron、無制限Browser Run、破壊的DB修正、自動購入は所有者の**明示的な事前承認なしに実行しない**。学習/検証用の合成テストデータを本番実績に含めない。

## 9. 次チャットへコピーする最短指示

> **RACE-AIの続き。GitHub `haji84/RACE-AI` の `docs/HANDOFF_RACE_AI_20261024_LIVE_ODDS.md` と Issue #67、Draft PR #71 を正本として最新状態を取得。10/24の芦屋6R、宮島3R、平和島3Rの締切10分以内の実オッズ変化とD1保存はすでに実証済みなので再計画しない。次はCloudflare Access付きiPhone Safariで実120組番の60秒再読込を確認し、許容ソース・費用制限の下で未来1Rの実60秒自動取得→D1→実機をE2E完成させる。安全な通常修正は既存PR #71に集約し、独立レビュー・重大変更の事前承認・0円/データ保護を守る。進捗は実際に確認できた証拠に限定し、GOALの4競技全R、T-10、オッズ/モデル分離、公式結果照合は維持する。**

---

引き継ぎ書は最新の動作を自動保証するものではない。**次チャットは実リポジトリ/D1の最新head・実データを再確認したうえで着手すること。**

## 10. 2026-10-24 12:05 JST 最終読取監査（次チャット起動基点）

**この節は、11:57時点の記録に対して別チャットから読み取り専用で再照合した追補。** Cloudflareから原本オッズを再取得せず、既存D1レコードを読むだけの確認を実施した。上記の事実やGoalは維持する。

### GitHubの照合

- PR #71の**この節追記前のHEAD**：`c0fcee319d92c3c5ff48de336002d08b7dbe602b`、ベース `codex/actions-four-sport-e2e`、`draft=true`、`merged=false`。本節をGitHubに書き込むことでHEADは更新されるため、次チャットでは必ず再取得。
- このHEADの[Actions #40056524126](https://github.com/haji84/RACE-AI/actions/runs/40056524126) は `completed/success`。**最新HEADの成否を別コミットのCIで代替しない。** 今後この文書を更新した場合は、その更新後HEADのCIを再確認する。
- Draft PR #64（B/LZH原本資産）、Draft PR #69（四競技基盤）、Draft PR #72（データ権利監査）も現時点でいずれも `open/draft/unmerged`。mainへの統合はしない。

### Cloudflareの再照合（2026-10-24T03:05:06Z = 12:05:06 JST）

**オーナー専用D1** `race-ai-odds-private-preview` に対してRead-only `SELECT` とAccess/Worker設定のGETを実施。次の値は再取得APIの返却実値。

| 設定・レコード | 確認値 |
|---|---|
| `odds_latest` | **4レース**、`20261024-04-03`・`20261024-17-03`・`20261024-21-06`・`20261024-21-07` |
| `odds_pilot_measurements` | 平和島3R **2**、宮島3R **2**、芦屋6R **1**、芦屋7R **3**、合計 **8件** |
| `odds_ingest_quota` | `2026-10-24 UTC` **6件使用**（他レース固有quotaは別テーブル） |
| D1テーブル | `odds_latest`、`odds_pilot_measurements`、`odds_ingest_quota`、`odds_pilot_race_quota`、`odds_pilot_capture_failures`、`odds_short_window_trial` |
| Worker `ODDS_REQUIRE_ACCESS` | `true` |
| Worker `ODDS_PREVIEW_READ_ENABLED` | `true` |
| Worker `ODDS_PREVIEW_INGEST_ENABLED` | **`false`**（実証に使った手動D1書込と区別） |
| Worker試験レース | `ODDS_PILOT_RACE_ID=20261024-21-07`、`ODDS_PILOT_MAX_UPDATES_PER_DAY=3` |
| Cloudflare Access | `RACE-AI Odds Preview - Owner only`、専用Worker向け・オーナー1件のみAllow |
| Worker Cron | **`schedules: []`（0件）**。毎分自動取得は未有効化 |
| Worker subdomain | `enabled=true`、バージョンPreview `previews_enabled=false` |

**重要**：上の8件は監査テーブルに保存された件数。芦屋6R等で保存しなかった最初の観測を含まない。登録されている最新4Rは当日すでに締切済み。過去レースのオッズは参考値と表示し、未来の値や発売中オッズと混同しない。GET確認であるため、発表時刻の新しい公式値が得られたと報告しない。

**再開前の実務警告**：Cloudflare OAuthのBilling/Usage系APIは403であり、同一Cloudflareアカウントの他アプリを含む使用量は未知。公式データの全国規模の60秒継続取得権利・提供元負荷・Browser Run無料枠も独立の課題。既存の取得回数カウンタ、403/429、422/timeout記録を無視して同日追加取得を行わない。

### 次チャットの作業者へ：この順序を守る

1. **このファイル・Issue #67・PR #71最新HEADを読んでから、Cloudflare D1/Access/CronをRead-only再照合する。** 実価格原本、トークン、所有者メールなどの秘匿値は出力しない。
2. **iPhone Safari実機受入が次の最小ゲート**。オーナーが過去レース（例：平和島3R）保護URLを開いてAccessにログインし、120通り/出典時刻/締切後参考表示を確認。時間差60秒でページが同一origin JSONを再確認するかをログと画面で検証。**元ソースオッズが更新されたことと、表示ページが更新したことは別KPI**。
3. 続いて、許諾・通信レート・無料枠の証拠を揃えた**未来の1レース**のみで、厳密な60秒自動取得→D1保存ハッシュ→Safari到達の本当のE2Eを受入。過去10月24日の検証を繰り返して「進捗」としない。
4. 本番全国展開、課金/一般公開、DB破壊的変更、正式モデル選択の差し替え、PR main統合は独立レビュー・事前明示承認なしに実行しない。すべての未達はGOALから消さず、`NO_FORECAST` / `STALE` / `SOURCE_UNAVAILABLE`などで理由を残す。

**このファイルを読んだだけで次チャットが自動実行されるわけではない。次チャットの最初の指示は第9章に記載。**
