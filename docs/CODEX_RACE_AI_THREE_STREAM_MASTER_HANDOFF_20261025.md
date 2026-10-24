# RACE-AI | Codex 3系統統合引継ぎ 2026-10-25（正本候補 v1）

**2026-10-25 最新GitHubヘッド・CI・並列作業所有権の再照合**： [CODEX_RACE_AI_GITHUB_VERIFIED_STATUS_20261025.md](CODEX_RACE_AI_GITHUB_VERIFIED_STATUS_20261025.md) を必ず併読。過去のSHAを最新として固定しない。

**Codexはこのファイルを最初に読むこと。** 続けて同階層の CODEX_RACE_AI_PARALLEL_RUNBOOK_20261025.md と CODEX_RACE_AI_START_PROMPT_20261025.md を読む。この文書のGitHub保存だけではCodex実行・main統合・完成を意味しない。

**Repository** https://github.com/haji84/RACE-AI
**最上位の採用GOAL** https://github.com/haji84/RACE-AI/issues/67
**Codex実行管理Issue** https://github.com/haji84/RACE-AI/issues/68
**3系統**：A 公式直前情報の合法取得・掲載前後の検知、B 実オッズ全組番・Cloudflare D1・iPhone、C 既存高度予想モデルと事前凍結・結果照合・PDCA。D 全体統合/独立レビュー/運用・実機品質。

## 1. 書き換えてはいけないGOAL

ボート、競輪、オート、競馬（JRA/地方）の全開催・全レースを、前日から発見し、販売締切の早い順に台帳化。三連単発売・結果評価可能なレースを全て主KPI分母に入れ、未予想/欠測/見送り/締切超過を隠さない。

予想は選手/馬の能力、近走、実コース/脚質/ライン/ハンデ/モーター/馬場/天候、事前の展示・試走等を適法・時点安全な特徴量として受け取り、全有効3連単組番から各モデル最大8点を**オッズ・人気・市場・他者予想・結果に一切依存せず**固定。ボート6艇なら120組。既存モデルの重みや過去のTop8を結果後に再調整し、当時の本命に見せかけることは禁止。

**公式直前情報が掲載されたらモデル入力の確認を開始**。以前の「締切10分以内でだけ展示を確認」という条件は廃止。BOATは展示、AUTORACEは試走、KEIRINは選手紹介/脚見せと根拠ある並び、競馬はパドックと当日馬体重を別イベントとして認識する。掲載が観測された事実と、元の初公表時刻・参加者ごとの必要な特徴量・利用権限が満たされたことは別。締切後に予想を増やさない。

予想モデル別の候補全件と最大8点を**本物の締切前に外部書込み・独立時刻証拠・SHA読戻しで不変保存**。公式結果（取消/失格/返還/同着/払戻/改訂）照合。モデルを同じ未来のレースで比較、原因を確認事実/仮説/不明に分けてPDCA。正式主指標 Hit@8_all = 事前保存8点で的中したレース数 / 三連単発売かつ公式結果評価可能な全対象レース数。全競技での実測98%以上は極めて高い**未達の挑戦目標**、保証禁止。1レースE2E/合成テスト/PRマージで最終完成と呼ばない。

UIはiPhone Safari。競技タブ、全レース、未予想理由、最新の前時点8点・根拠/証拠リンク、モデルごとの的中/不的中、公式結果revision、払戻、日/週/累計、並替/検索。自動投票・決済なし。追加料金0円志向、ZBook/DELLの常時稼働不要、GitHub Actions中心、Cloudflareの非公開配信は必要最小。追加費用、Secrets/権限/保護解除、外部公開、破壊的DB操作、元データ大量転載は必ず所有者の**事前Human Gate**。

## 2. GitHubの既存資産（2026-10-25確認時点。Codexは再fetch必須）

| 正本・提案 | head SHAとbranch（将来変わるため再取得） | 役割と注意 |
| --- | --- | --- |
| [Issue #67](https://github.com/haji84/RACE-AI/issues/67) / [#68](https://github.com/haji84/RACE-AI/issues/68) | owner採用Goal / Codex P0 | 不変の採用範囲・順序・安全制限 |
| [PR #61](https://github.com/haji84/RACE-AI/pull/61) | fef68607b4773c59d6d46aa04b9e9762a42683d4 ; docs/requirements-progress-v1 | Draft。53章要件、AGENTS.md、PROJECT_STATE.md、ROADMAP.md、Codex統合優先仕様。mainにあると見做さない |
| [PR #64](https://github.com/haji84/RACE-AI/pull/64) | 761247bee0209e37b1af6b8885e92cad3e9260a5 ; codex/race-ai-completion | Draft・巨大514files。BOAT B/K・ST/近走/公式結果/DB・不変証拠など。停止したPOST・nonceは再送しない |
| [PR #65](https://github.com/haji84/RACE-AI/pull/65) | 989ffff1d6d2a3476dab41655038eda43f94fff7 ; feat/completion-controller-pilot-20261016 | Draft、完成責任Controllerのread-only pilot。無人実稼働は未実証 |
| [PR #69](https://github.com/haji84/RACE-AI/pull/69) | bca59ebc5c7174e79d2dba027a97890f5d0d3d1 ; codex/actions-four-sport-e2e | Draft、4競技合成E2E。PR71/72の共通base |
| [PR #71](https://github.com/haji84/RACE-AI/pull/71) | a3d4d011fab8773e2eab07ca83580ab345dfb708 ; feat/four-sport-forecast-audit-view-20261022 | Draft。高度予想・比較・オッズ/Cloudflare/owner-only iPhone配信が同じPRにある |
| [PR #72](https://github.com/haji84/RACE-AI/pull/72) | 386d33ca57d748ed663ccd9acb34c1e5f146bc17 ; feat/p0-offline-discovery-gate-20261022 | Draft。公式掲載トリガー・データ源B/K・JRA/KEIRIN/AUTORACE監査・権利/時点・欠測。今回のhandoff文書をここに置く |
| [Issue #66](https://github.com/haji84/RACE-AI/issues/66) | Cloud hosting cost and release | 本番移行未実証。毎commit課金ビルドや自動公開をしない |

**重要**：PR #71と#72はPR #69をbaseとした**別ブランチ**。両者が既に相互統合されていると判断しない。PR数が非常に多く、親子関係や同名機能の重複がある。既存PR差分/head/base/CIを照合し、PRは再利用、新規PR乱立と無承認の一括Merge・force pushは禁止。mainはこれらの研究機能が統合済みではない。実装コード・テスト・実機配信・正式稼働を別々に扱う。

## 3. A：直前情報・展示/試走/選手紹介・馬体重・パドック（主 PR #72）

- BOAT：PR64 B/Kアーカイブと公式beforeinfoの当日実取得、同一6艇・展示ST/展示タイム・風波の単発実験あり。近走Kを合法な用途・公表時刻・登録番号で実モデルに統合し切っていない。真の風向→コース方向、water wet factorの根拠も未達。
- BOAT全日B 14会場168Rの予定締切を昇順抽出して最初の近い2候補の公式直前ページを確認する実験は成功。旧「残り2〜10分」条件は**2026-10-24にownerが正式撤回**。今の方針は公式beforeinfoがAVAILABLEとして観測されたら入力検査起動、遠くてもよい。
- AUTORACE：伊勢崎11R公式ページの5時点HTTP200 + source SHAは保存したが、当該Rの車番に対応する**実試走T数値の抽出は未成立**。昔の「伊勢崎は開催中止」という結論は**汎用HTML中止バナーの誤判定で撤回済み**。 [訂正と実証](https://github.com/haji84/RACE-AI/blob/feat/p0-offline-discovery-gate-20261022/docs/P0_NONBOAT_TRIAL_ACTUAL_CORRECTION_20261024.md)。
- JRA：京都12R公式出馬表のmeta Shift_JIS→CP932を実解読、日付・場・R・馬体重**欄**を確認。しかし馬IDに結合する当日馬体重の数値・「発表済」前後2観測は未達。パドック映像は別媒体・別権利。
- KEIRIN：KEIRIN.JP開催日程HTTP200は実証、しかし特定Rの本物の選手紹介/脚見せ/ラインについて、配信ソース/掲載変化/分析権限は未取得。スケジュールや中継ボタンを選手紹介済みと誤認しない。
- 共通オフライン遷移器は race_ai/four_sport_presentation_trigger.py および race_ai/four_sport_publication_transition.py。PENDING→AVAILABLE/PARTIAL、source SHA・時刻・race/参加者同定、二重通知抑制は**合成PASS**。無人公式掲載監視とprovider固有の合法取得方式は未完成。

**A Done**：AUTORACE、JRA、KEIRIN各1実レースで、公式合法ソースをrace/参加者と照合し、発表前と発表後の異なる**実時点2観測**からPENDING→AVAILABLEを再現、欠測や中止の負例もPASS。規約・許される取得頻度・個別の収集/私的保存/分析/派生表示/映像の目的権限が認定されて初めてPR71に昇格できる。無許諾ならBLOCKEDを正直に記録し合成/設計は進める。

## 4. B：4競技全組番オッズ/Cloudflare D1/iPhone（主 PR #71）

**過去の公式オッズは未取得ではない。** 正本 [Odds handoff 2026-10-24](https://github.com/haji84/RACE-AI/blob/feat/four-sport-forecast-audit-view-20261022/docs/HANDOFF_RACE_AI_20261024_LIVE_ODDS.md) 全文を読む。

2026-10-24のBOATRACE公式odds3tの限定手動Browser Run実験で、以下は**実値120/120取得**：
- 芦屋7Rは3観測・公式オッズの掲載時刻と値が変わらず、無意味な二重上書きなし。
- 芦屋6RはT-6分/T-4分、8組の見比べで8/8変化、最新120値をD1保存/SHA照合。これを120値がすべて変化したと拡大表現禁止。
- 宮島3Rは全120/120値変化、D1保存2版のhash readback PASS、保存間隔約86.8秒。
- 平和島3Rは118/120変化、D1保存/readback PASS、間隔約101.2秒。3回目Cloudflare Browser RunがHTTP422/code6002 timeout。
- Cloudflare Browser Runの429/code2001あり、BOATRACE側の429と混同しない。Browser Run全国毎分に無条件拡大不可。

**以前の照合時点**：private D1 race-ai-odds-private-preview に上記4R分の最新120件、試験監査/Quota台帳。Owner-only Worker・Cloudflare Accessを保護、read=true・ingest=false、無人cron停止。**本番状態は必ずread-onlyで再検証**。Cloudflare API/Access JWT/owner email/worker private IDをpublic GitHubへコピペ禁止。PR71のcode headとCloudflare実配備SHAは一致未確認。

**未達**：iPhone Safariの所有者Accessログイン・120組表示と**60秒間隔3周期の実機確認**、継続許可された未来1Rの公式全120取得→D1→iPhone自動更新、4競技全レースへの展開、Cloudflareアカウント他アプリ込みの無料枠残量実測（以前Billing Usage API HTTP403）。GitHub CIやD1 readbackだけでiPhone受入PASSにしない。

**展示の公表トリガーとオッズ毎分の開始窓を混同しない**：モデル入力検査は直前情報掲載観測時に始めることが**決定済み**。PR71の現行 odds_refresh_plan.py はT-60分毎分のシナリオ。一方ユーザーは**T-15またはT-10分から毎分**の費用低減案を検討したが、このchatで正式最終選択は確認できない。SPEC_CONFLICTS.mdにT-60 vs T-15/T-10の権利・予算・負荷比較と採否保留を載せ、勝手に変更しない。上流元オッズが60秒で変化しなくても、D1/画面リフレッシュの成功・失敗と区別する。

**B Done**：合法・許容頻度/容量を確認した未来1Rで全120（他競技は参加数の全有効3連単）、本物の公式時刻/取得時刻→owner-only D1保存/SHA読戻→iPhone Safari実画面60秒×3周期を証明、アカウント共有の料金/usageとquota監査を満たす。その後全開催/4競技へ拡大。Access解除・無断本番公開・有料化は禁止。

## 5. C：高度モデルと結果PDCA（PR64/PR71が正本、PR72接続）

- PR61の53章・PR64のK履歴/同一実進入ST/モーター・展示/結果解析を分類し、PR71の boat_multi_feature_models.py、boat_feature_adapter.py、comprehensive_four_sport_models.py、four_sport_matchup_models.py、four_sport_model_suite.py、four_sport_learning.py を**新規作り直さず**再利用。3指標B-LITEは比較ベースラインのみ、最終モデル扱い不可。
- 既存モデル群：総合要因 / 複数シナリオ / 条件付き1着→2着→3着 / 先行・追走・波乱の着順展開。現状主に**未学習/未校正の研究用係数**。合成全組番・8点PASSでも実際の未来レースに接続したと主張しない。
- 合法・時点安全な公式出走/近走/会場条件とソース出典・許諾・sample_n・published_at・captured_at・as_of・transform_idをそろえる。PR72 boat_existing_asset_integration.py 等を再利用。元Bのfirst_observed_atを勝手に発行元published_atと同一視しない。過去Kを現在の予想に後付けして自己採点しない。
- **各モデル同一の前時点snapshot**で全有効3連単を計算、モデル別8点の根拠と不確実性、例えば外枠6号艇1着なら進入や展開/STの根拠が本当にモデルに入ったか説明。予想凍結後の価格は説明の経済性欄だけに表示し、順位評価の入力から完全分離。
- 全レース台帳（欠測・見送りも含む）→独立時刻付き予想原本/再読戻し→公式結果改訂照合→前向きモデル別/競技別Hit@8_all・原因PDCA、iPhone Safari受入へ。
- 時間について、**直前情報の掲載検知はT-10に限定しない**。別の予想ユーザー公開目標としてPR71のT-10min契約があり、未掲載/最終直前のデータとの矛盾は事前時刻の実際の証拠とOwner判断で扱う。締切後にT-10達成と後付けしない。

**C Done**：最低1未来レースで真の許可済みソース→既存高度モデル全組番→各8点を**締切前に外部不変保存**→公式確定結果・改訂/返還照合、iPhoneでモデル別根拠表示。さらに4競技・全対象の主KPIとモデルの将来改善検証を実施。98%は未達なら未達と報告する。

## 6. 横断の分離/独立レビュー/Human Gate

共通のsource_race_id, sport/venue/event_date(JST)/cutoff revisions, provider URI/SHA, source_first_published_at(unknown可), captured_at, policy rights evidence/purpose, model_id/version, input snapshot SHA, frozen_at/independent receipt, official result revision, odds source/capture/received_at/client-rendered_atを別フィールドで扱う。

- **CodeRabbitは使用禁止**。実装担当と独立したAI-09/別モデルに設計および差分の独立批判レビューをさせる。AIコメント≠GitHub APPROVED。正当なGitHubレビュアーと正式なHuman Gateを飛ばしてmain/公開しない。
- 公開GitHubにはprivate D1 row/API credentials/owner identity/Access JWT/元の競走映像・生オッズ全行/許諾のないソース・選手個別解析を記載しない。
- 既存PRを再利用しながら**並列開発**。ただしPR71にはB・Cが同居するためブランチ全体のwriter lock＋expected-HEAD compare-and-swapを用い、同時上書きをしない。PR72（A）とPR71（B/C）とPR69（共通）でpath ownershipとatomicな作業台帳を使う。プロセス/Ownerが権限確保していないCloudflare worker/本番設定を勝手に更新しない。
- 外部権限・コスト・一般公開・危険なDB変更・ルート設計変更・source rights推定・大規模pollingは**個別所有者承認必須**。この引継ぎは包括承認ではない。
- 予定より遅れた/未着手を「完了」と偽らない。各作業で正本HEAD、PR、CI、実データ/合成の区別、reviewer ID・指摘根拠、独立実機、次のクリティカルblockerを記録。

## 7. 最初のCodex実行順（詳細はrunbook参照）

1. 本書/実行Runbook/Start Prompt、Issue #67/#68、PR #61/#64/#65/#69/#71/#72の最新head/base/CIと実ファイルを読み直す。mainはREADME中心・stacked Draft未統合の状態を再認識する。
2. SPEC_CONFLICTS（オッズT-60/T-15/T-10、直前掲載時点 vs T-10予想公開、権利・公開・保護境界）とASSET_REUSE_MATRIX、SOURCE_RIGHTS_MATRIX、GOAL_EXIT_GATESをレビューする。
3. 最初に共有ID/データ権利/出典・締切/不変レシート/モデル価格分離のcontractを独立テストし、A/B/C各laneを**必要数だけ動的並列**にする。単一既存PRへの書込みは直列で競合避け。
4. 1Rの本物の安全E2Eに至る最短の依存を先に解消し、CI・独立レビュー・修正・受入を繰り返す。権限がない公開サイトの自動取得だけHOLD、他の安全工程は止めない。
5. 実機・Cloudflare/iPhone/外部レビュー/人的承認が欠けたら、残りをBLOCKEDと明示し、次に人間がすべき1つの操作と証拠をIssue #68へ残す。**Codexがチャット外で無期限に働き続けるとは主張しない**。無人継続はGitHub Actions等の実稼働/再起動実証を経て判定する。
