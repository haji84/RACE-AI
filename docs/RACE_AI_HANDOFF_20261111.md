# RACE-AI 詳細引き継ぎ正本（2026年11月11日）

## 最新追記：2026-11-11・run43038009675の実原本・実Pages・後続読戻し

**同じ元P0原本の保全、別runnerでの独立読戻し、既存公式照合、既存Pagesでの実表示確認まで合格した。14レース・28予想のうち13レース・26予想を採点し、通常完走以外の状態を含む1レース・2予想はHOLDを維持。後続dailyと4日分のAES読戻しも成功したが、別処理の集計をこの元P0採点結果と混ぜず、全履歴完了とは判定しない。**

- 今回も元run `42995325741`、artifact `13842474540`、元ソース `e24f09f150e2318dd16a96bdc6db1d8c1317b9ae` の同じ原本を使用。保全commit `2448b33de6ecf7388f8fd8577860622b67b9b9a2` と元receipt `20fc291429003fd0351baef4b0c1918b76b4e066` を固定し、新予想作成・原本書換え・復旧処理からの公式情報取得は0。
- [保全job130581941861](https://github.com/haji84/RACE-AI/actions/runs/43038009675/job/130581941861) はrunner `1000042267`、[独立読戻しjob130582152757](https://github.com/haji84/RACE-AI/actions/runs/43038009675/job/130582152757) は別runner `1000042268` でsuccess。既存読取器が14レース・28予想・2モデルの原本結合と締切前保存を再検証した。
- [照合・実Pages job130582378667](https://github.com/haji84/RACE-AI/actions/runs/43038009675/job/130582378667) の元P0専用集計は、保存済み公式結果14レース、採点13レース・26予想、HIT6、MISS20、`ABNORMAL_FINISH_REVIEW_REQUIRED` 2。採点SHA `e8a142ca13b1b968b2958b4ee49c78ff54037f3d3fbddb49769ec4a954bafedb` と原本文書集合SHAは前回run43034336347から不変。HOLDを不的中へ変換していない。
- 保存済み暗号化runtimeと既存TERM readerによる表示名補充を実行し、対象日の延べ84出走枠で名前あり84、登録番号と検証済み名簿に結び付いた名前84、欠損0。延べ出走枠数であり、84人の異なる選手という意味ではない。予想辞書・買い目・入力・採点には適用していない。
- 実Pages検査時の暗号化表示feedはgeneration `115`、commit `439b697b1df95d19c82ab3ae9df6f05eab9ca6fc`。実Pagesは `2026-11-11T14:26:20.661Z` に `LIVE_OWNER_SITE_VERIFIED`。検査日11/11・明示stage P0で、対象artifact・原本JSON SHA・元コードコミットとの一致、原本監査表示、P0詳細、2モデル群、14結果を確認した。
- 幅320・390・1440の3種類で検証し、モデル切替は3画面・原本検査6件、表示名検査も合格。鍵がrequest/storageへ入った事象は検査範囲で0、公式情報取得0、平文公開false。28枚全カードを個別検査したという証拠ではない。
- この実画面検査は締切後で、`future_native_visible_before_cutoff=false`。今回、未来レースの画面表示を締切前に観測したとは主張しない。元原本が締切前に保存された証拠14レース・28予想とは別の判定である。
- 名前接続のproductionは [`ba2d2d698b90548dd67b6ca7ac2dada776b09e32`](https://github.com/haji84/RACE-AI/commit/ba2d2d698b90548dd67b6ca7ac2dada776b09e32)。[PR #154](https://github.com/haji84/RACE-AI/pull/154) でmain [`15047c84de0b44126dc97f85ca5ff0b66bb7eeab`](https://github.com/haji84/RACE-AI/commit/15047c84de0b44126dc97f85ca5ff0b66bb7eeab) に統合し、この固定組で実行した。表示名のassertion、既存モデル、既存採点器、AES形式は変更していない。

### 後続dailyと判定を分ける

[後続daily job130583568151](https://github.com/haji84/RACE-AI/actions/runs/43038009675/job/130583568151)、runner `1000042271` はsuccess。run全体は `2026-11-11T14:27:53Z` にcompleted successとなった。既存 `verify_all_history_pdca_readback` の4日分AES readback coverageはtrueだが、`all_history_completion_proven=false`。全体ledgerの未完了54レース・未採点498予想を今回の14レース・28予想へ転用しない。

判定差の所在は実ログと既存コードで確認済み。元P0の [`frozen_day_cycle.settle`](https://github.com/haji84/RACE-AI/blob/ba2d2d698b90548dd67b6ca7ac2dada776b09e32/race_ai/frozen_day_cycle.py) は照合対象の出走者全員が `FINISHED` であることを要求し、異常状態をHOLDにする。一方、日次の[既存bulk集計](https://github.com/haji84/RACE-AI/blob/ba2d2d698b90548dd67b6ca7ac2dada776b09e32/race_ai/retained_model_pdca_audit.py) は認証済みの確定結果・払戻・返還条件で評価し、この全員通常完走条件を持たない。これらの判定部分は修復前 `997535d388e8dd6609355fde6f94e90307f818a3` から不変で、名前補充によってHOLDが解除されたのではない。

| 今回原本に対する既存処理 | 実測 | 判定の扱い |
|---|---|---|
| 元P0のnative評価 | 13レース・26予想採点、HIT6・MISS20・異常HOLD2 | 今回の原本照合結果の正本。HOLD2を維持 |
| 後続dailyの11/11集計 | 14レース・28予想、eligible28・HIT6・MISS22・unresolved0 | 別規則の参考集計。元P0のHOLD解除や全履歴完了の証拠へ統合しない |

### 次の1工程

既存の翌朝P0/P1起動枠が実際に発火することをrun・呼出先jobで確認し、次の真正な原本について、新規receipt PUTの応答コミットを指定したGETが実環境で一致することを証明する。今回の回復は既存receiptを再利用したため、新規PUT経路は回帰テストで検証済みだが実地証明はまだない。定期設定の存在を翌朝の完走保証とはしない。

今回のP1は元runがその前に停止したため未生成であり、後付けでは作らない。翌朝の既存起動枠の実発火、未来レースでのP0/P1完走、全日・全国・4競技・全現役モデルの完成は、この回復実行では未実証。対象分母は14レース・28予想で、要確認の1レース・2予想も残す。

### 最新の安全な証跡

- [run43038009675](https://github.com/haji84/RACE-AI/actions/runs/43038009675)
- [独立読戻し](evidence/2026-11-11/first-p0-independent-readback-43038009675.json)
- [元P0の照合・表示名84/84](evidence/2026-11-11/first-p0-reconciliation-43038009675.json)
- [実Pages検証](evidence/2026-11-11/first-p0-pages-43038009675.json)
- [対象原本を固定した検査コンテキスト集計](evidence/2026-11-11/first-p0-site-context-counts-43038009675.json)
- [後続daily・履歴読戻しの安全な集計](evidence/2026-11-11/first-p0-historical-readback-counts-43038009675.json)
- [今回の実証全体と限界をまとめた固定証跡](evidence/2026-11-11/first-p0-production-proof-43038009675.json)
- [修復・保全・失敗履歴を含む詳細](evidence/2026-11-11/first-p0-readback-repair.md)

## 修復途中の実証：run43034336347までの履歴

以下は名前接続修復前の記録。ここでの「進行中」「次工程」は当時の状態であり、最新判定は上記run43038009675の欄を優先する。

**最優先の原本保全と別runner読戻しは合格。元P0に限定した公式照合は13レース・26予想を採点済み、1レース・2予想は通常完走以外の状態を含むため確認待ち。表示を含む最終一巡判定は、下記の実ブラウザ検証が未合格のため保留。**

- 対象は元run42995325741、artifact13842474540の同じ14レース・28予想・2モデル。予想の再生成・締切時刻の書換えは0。
- 既存AES vaultへの保全はrun43030625791で成功。固定commit `2448b33de6ecf7388f8fd8577860622b67b9b9a2` にP0・CONTINUITY・SOURCE_CONTROLの3原本を保管。run43034336347でも `EXACT_ORIGINAL_VAULT_UNCHANGED` を確認。
- 元JSON SHA `9073715a51b145efe77b612d4a9fd4ec2739e8c617ee3840b7751c30769ad1b4` と元暗号文SHA `f4df5195e7376dce82550c8f54354bf49cf2a661bd3956b4e6fe8020c9ff390d` は一致。元保存時刻 `2026-11-11T09:29:52Z` を維持し、14レース・28予想の締切前保存を検証済み。
- 最終再読戻しの保存job130569119250はrunner1000042247、読戻しjob130569362570は別runner1000042248。両方success。
- 結果未取得だった初回HOLDを保存した後、既存daily collector run43015122597のattempt2・3だけを実行。各12リクエストの上限を維持し、結果保存generation63／commit `e95d01b35f96cafff9d0313db80e2eb7ab647cac` を取得。
- run43034336347の既存採点器による今回P0専用結果は、公式結果14レース、採点13レース・26予想、HIT6、MISS20、`ABNORMAL_FINISH_REVIEW_REQUIRED` 2。この2件を不的中へ変換しない。全体feed146レースの件数から換算していない。
- 同runの暗号画面はgeneration114／commit `073d1682563b2daf8005a7c9f016742b469f84ef`。原本辞書・予想SHAは不変。
- ブラウザstepは `LIVE_OWNER_SITE_REJECTED`、checker line233。P0投影は登録番号だけを持ち、復旧wrapperが既存の認証済み名簿による表示名補充を未接続だった。表示名の修復を進行中。名前のassertion、予想原本、既存採点器を緩めない。
- `FIRST_RECEIPT_INDEPENDENT_READBACK_MISMATCH` の実装修正はcommit `a60b8493ee67f8cf1006d3c240ffd121a5f359ce`。Contents PUTが返す作成コミットへ独立GETを固定。元receipt `20fc291429003fd0351baef4b0c1918b76b4e066` は保存内容が一致し、変更していない。当時の失敗GET応答が未保存なので、キャッシュ・GitHub障害とは断定しない。
- PR152・153をmainへ統合済み。直近実行のmainは `c0ed237f3cce89e70c3b894ec6e339c8a90bc3e8`、その実行で使ったproductionは `a6458be1f49924911f1352a5f2b9f6bb46d66115`。新しい修正を反映する際は必ずHEADを再取得し、全pinを揃える。

### この時点の次工程（履歴）

既存の暗号化runtimeとTERM名簿readerから表示用の名前だけを既存mergerへ接続し、同じ元原本で公式照合・既存Pages検証を再実行する。実画面はartifact ID・JSON SHA・元コードコミットへ対象を固定し、代表原本詳細・モデル群・モデル切替を検証する。28枚全カードを個別検査したとは報告しない。

今回のP1は元runがその前に停止したため未生成であり、後付けで作らない。翌朝の既存JST06:20および07:02–08:57枠は残しているが、未来の発火・P1完走はまだ実証していない。全日・全国・4競技・全現役モデルの完成でもない。今回の原本14レース・28予想を分母とし、要確認の1レース・2予想を除外しない。

### 今回の追加証拠

- [修復・実保全の詳細](evidence/2026-11-11/first-p0-readback-repair.md)
- [元原本の独立読戻し](evidence/2026-11-11/first-p0-independent-readback-43034336347.json)
- [今回P0だけの公式照合](evidence/2026-11-11/first-p0-reconciliation-43034336347.json)
- [最終実行43034336347](https://github.com/haji84/RACE-AI/actions/runs/43034336347)
- [結果照合・ブラウザ確認job130569667243](https://github.com/haji84/RACE-AI/actions/runs/43034336347/job/130569667243)

---

## 以下は修復開始前の引き継ぎ記録

以下の「本番一巡0件」、旧HEAD、未解決状態は修復前の履歴として保持している。最新判定・次の作業は上記追記を優先し、GitHubの最新状態を再取得する。

> **更新基準：2026-11-11 21:48 JST以降にGitHub実環境を再確認。**
> この文書は次のChatへの引き継ぎ資料であり、CI成功や「今後の予定」を実レース実証と混同しない。次のChatでは**最初にGitHubの最新main・production HEAD・Actions・保存artifactの現存状況を再取得**すること。
> 秘密鍵、個別選手の非公開データ、暗号復号鍵、予想の平文はこのPublic文書へ載せない。

## 0. 結論・次の1手

**本番一巡合格は0件。ただし、11/11に本物のボートP0予想候補を生成し、AES暗号化してGitHub Actions artifactにアップロードするところまでは到達した。**

次に解消する一番の障害は run **42995325741** における
`FIRST_RECEIPT_INDEPENDENT_READBACK_MISMATCH` である。

- **すでにある暗号化原本を最優先で保全・照合する。** 同じレースを新たに予想し直して既存原本を上書きしない。
- 原因特定後、正本の一致するリリースコミットにmainの起動条件を整合させ、**未来レース**で「P0/P1生成→AES保存→別ランナーの独立SHA読戻し→既存公式結果照合→既存画面表示」まで実証。
- **新規モデル・新規照合器・新しい起動方式を増やさない。** 既存コードの本番経路を一本化する。

## 1. 不変の最上位GOALと承認済みの運用条件

1. **4競技**（ボートレース、競輪、オートレース、競馬）の**全対象レース・全現役モデル**を最終対象とする。取れないレース・適格性を満たせないモデルも `NO_FORECAST` / `HOLD` として分母に残す。
2. ボートは既存の展示前P0と展示後P1、競輪は既存PR #71の**独立4モデル**を正本とする。同じ買い目を別モデル名で複製しない。
3. 未来レースの予想はモデル版・入力SHA・予想SHA・レースID・実保存時刻を固定する。締切前の投票可能な予想と、締切後・発走前の研究予想を時刻で分ける。発走後の後付けは正式予想に採用しない。
4. **既存AES暗号保存**を継続。公開GitHubには暗号文と必要最小限の証跡のみ。別GitHub-hosted runnerで本物の暗号原本を独立復号し、SHAと時刻、レースIDを照合する。
5. 結果は**既存の公式結果取得・原本照合エンジンだけ**を使う。新しい照合器・結果の補完捏造を追加しない。モデル別的中・不的中・回収率・損益・万車券捕捉・カバー率、学習/改善を追跡する。未認証結果は採点しない。
6. レース一覧、モデル別買い目、保存日、公式結果、照合判定は既存GitHub Pagesで表示。UIが復旧しても予想生成が復旧したとは見なさない。
7. **Public維持、GitHub Actions主体、PC不要、Vercel不使用**。余計な新API契約は要求しない。個人用公開ページ取得経路の2026-11-09承認は既存GitHubの設計条件。サービス規約・負荷制限・403/429停止は維持する。
8. 重大な権限・セキュリティ・課金・構造変更はユーザー事前承認。ただし **2026-11-11に既存ボート取得固定境界解除とPR #145のmain統合、限定 `actions:write` はすでに明示承認済み**。同じ承認を何度も求めない。

**合格の唯一の基準：未来の実レース原本と公式結果が同じレースID・モデルID・SHAで結ばれ、締切前保存→別runner独立読戻し→既存照合器で結果確定した証拠。** 合成テスト、CI成功、GitHubスケジュール登録、画面表示のみでは完成としない。

## 2. 再確認したGitHubの最新正本（調査時点のスナップショット）

- Repository: https://github.com/haji84/RACE-AI
- 公開属性: **Public**。default branch: **main**。
- `main` HEAD: `686ea73ecfa6b2819d2d8a60442901e6fb0f4d4e`
- P0/P1 owner release: `production/boat-p0-p1-20261111` HEAD `997535d388e8dd6609355fde6f94e90307f818a3`
- `gh-pages` HEAD: `cc963d4f797680d9967d2d7e828cf17f0d1cc1d2`
- 暗号化されたBOAT保存表示履歴 `state/boat-saved-view` HEAD `751bef3a1586c538ac5086d62279d84aca2c724c`。`latest.json`: V5、generation **109**、view ID `a633cc1a07180124846688e8a232fdbfb43fdcd95f57d7037177b46d538b719c`。これを11/11の新P0正式認証と誤認しない。
- `state/boat-all-model-forecasts` HEAD `72c7bc466bd4b6327717019ec3a56b89b9cde1f0`。`latest.json`が参照する原本はrun **42840665143**（11/10）。11/11の今回の新P0ではない。
- GitHub Pages: https://haji84.github.io/RACE-AI/。保存URLフラグメント内の復号鍵を公開コミットに貼らない。

### 主な正本ファイル

- `main/.github/workflows/boat-racer-daily.yml`: 日次・5分ごとの既存結果取得、`source_mirror`、既存結果照合、`owner_p0_p1_dispatch`。
- `main/scripts/boat_main_dispatch_gate.py`: JST日・正本SHA・取得担当境界・過去実行の単一起動/証拠チェック。
- `main/.github/workflows/boat-nationwide-ab-one-shot.yml`: **workflow_dispatch登録用stub**。main上でP0/P1実行はしない。
- `production/boat-p0-p1-20261111/.github/workflows/boat-nationwide-ab-one-shot.yml`: **実際のP0/P1 owner worker**。既存のfirst P0・追加P0・P1・AES原本・継続制御・従来結果照合。
- `production/boat-p0-p1-20261111/scripts/first_p0_bootstrap.py`: first-P0候補生成、暗号artifactへの保全、index登録、サーバ読戻し検証。
- `production/boat-p0-p1-20261111/scripts/boat_private_original_archive.py`、`scripts/github_existing_cycle.py`、`scripts/boat_all_model_cycle.py`、`docs/RACE_AI_LATEST_STATUS.md`。

## 3. BOAT修復の統合履歴と未統合分

既存の`feat/four-sport-forecast-audit-view-20261022`にあったP0/P1モデルと、mainの結果取得が分断されていた。モデルの精度以前に **予想起動が旧ブランチのpushに依存し、結果取得・照合はmainの別ワークフロー**で動いていたことが最初の大きな停止原因。

**mainへ統合済み（2026-11-11）**
- PR #142: 元のP0/P1を専用workflow_dispatchから実行可能にする修正。
- PR #144: mainに同名workerの登録stubを作成。
- PR #145: mainの既存result workerから元P0/P1を起動し、既存結果照合へつなぐ経路。制限付き`actions:write`、承認済み。merge SHA `543d07b1e28660279f26b4075094915358eeb8e3`。
- PR #146/#147: source-free確証付きで初回所有者起動。
- PR #149/#150: 最初のソース取得**前**に旧テストが失敗したrunに限り、安全な1回のリトライを証跡から許す。

**未統合・注意**
- PR #148（Open）: `production/boat-p0-p1-20261111`上の旧テスト修正。旧テストは新たに承認済み`workflow_dispatch`を禁止しており、コードとの整合性修正のためのPR。HEAD `997535d388e8dd6609355fde6f94e90307f818a3`。本番原本やモデルを修正したものではなく、CI緑は本番証明ではない。baseは旧開発ブランチなので**単純マージで実行系が混ざらないよう注意**。
- PR #143（Draft）: 別のBOAT本番入口修正案。PR #145と重複するため安易に統合しない。
- PR #108ほか研究コード: 現在のP0/P1本番正本へ無断採用しない。

### ユーザー承認と取得固定境界

- 2026-11-11、ユーザーは「承認する」と明示。
- `production/.../docs/RACE_AI_LATEST_STATUS.md`末尾に `RACE_AI_SOURCE_OWNER_BOUNDARY_RELEASED_V1` の正式承認追記あり。過去の `ACTIVE_FULL_FIRST_TO_FIXED_ATTEMPT_TWO_BOUNDARY` 記録は削除せず保持。
- 旧HOLDは過去の記録として残すが、解除以降の新実行に限り実行可能。403/429停止・ソース取得上限・暗号保存・単一writer・公開範囲を変えない。

## 4. **最重要：11/11 実レースP0候補生成・暗号保存の本番証拠**

### 実行1: run 42993305843（18:13 JST頃）

https://github.com/haji84/RACE-AI/actions/runs/42993305843

- release SHA `5f5bd960e3377a87541f9d6b348d3c045ea51cf0`。
- 本番起動と所有者解除・SHAのゲートは通過。
- 旧`tests/test_cycle_workflow_references.py`の3件が`workflow_dispatch`を禁止して失敗。
- 実P0/P1作成・保存・ソース取得はスキップ。source code bundleのみ。**予想原本なし**。この失敗を「実レース予想失敗」に計上しない。
- その後のPR #148等は旧条件の更新。根拠なしのリトライ一般許可にしてはならない。

### 実行2: run 42995325741（18:27 JST頃）

https://github.com/haji84/RACE-AI/actions/runs/42995325741

**ここが今いちばん重要。**

- release SHA: `e24f09f150e2318dd16a96bdc6db1d8c1317b9ae`。
- 本番起動・所有者ゲートを通過し、既存first P0取得は `FIRST_P0_CREATED_PENDING_SERVER_RECEIPT` と記録。
- **14レース、28予想エントリ相当**（ログの `races:14, models:28`）。28を「28独立モデル完走」と読み替えない。全対象レース・全モデル分母は別に検証。
- 予想JSON SHA256:
  `9073715a51b145efe77b612d4a9fd4ec2739e8c617ee3840b7751c30769ad1b4`
- 既存AES封印結果 `PRIVATE_ORIGINAL_ARCHIVE_PACKED`。
- AES暗号文SHA256:
  `f4df5195e7376dce82550c8f54354bf49cf2a661bd3956b4e6fe8020c9ff390d`
- 内包ZIP SHA256:
  `6dd78cac4469f93dde29bd29817d3dfc79c53d782fb42c687ab32ac65ab096ba`
- 暗号artifact `boat-p0-existing-42995325741`、ID **13842474540**、サイズ **83,849 bytes**。調査時点では`expired:false`。
  https://github.com/haji84/RACE-AI/actions/runs/42995325741/artifacts/13842474540
- 追加の暗号化継続データ `race-cycle-continuity-42995325741` ID **13842779131**、`race-source-control-42995325741` ID **13842973909**、コードbundle `existing-cycle-source-42995325741` ID **13842369916**。
- **しかし `first_p0_bootstrap.py finalize` のサーバ側初回receiptの読戻し検証で `ValueError: FIRST_RECEIPT_INDEPENDENT_READBACK_MISMATCH`。実行conclusionは`failure`。**
- そのため元の追加P0、P1、owner-view表示、結果照合へは進まなかった。**本番一巡合格は0件**。暗号artifactに保存されたことと、正式な原本の独立認証完了は別。
- **ユーザーに実際の同じレースを再予想して上書きすることは提案しない。まずこの存在済み暗号artifactを検証・保全する。**

### 実行3: mainのschedule run 43015122597（20:49 JST）

https://github.com/haji84/RACE-AI/actions/runs/43015122597

- event=`schedule`、main SHA `686ea73e...`、全体`success`。
- `daily`結果取得は成功。ただし **`owner_p0_p1_dispatch` はskipped**。`source_mirror`と独立結果照合もskipped。
- **定期起動自体は存在する**。20:49 JSTの実行はP0起動専用スケジュール条件外のため、そこでownerジョブがskipなのは起動不能の証明にはならない。次の該当早朝予定枠で改めて実運用を確認。
- main結果workerの全体successをP0/P1予想完走と混同しない。

## 5. `FIRST_RECEIPT_INDEPENDENT_READBACK_MISMATCH` のコード上の停止点

release版 `scripts/first_p0_bootstrap.py`：

1. `capture-wait`が実P0候補を`boat_all_day_output/forecasts.json`として生成。
2. `scripts.boat_private_original_archive pack --kind P0`でAES暗号化。GitHub artifact uploaderは実ファイルを受領。
3. `finalize --artifact-id 13842474540` はartifact run ID・名前・GitHub ZIPを確認し、ローカルのforecasts JSON SHAが元indexのSHAと一致することを確認。
4. `register(day,raw,meta)` がcreate-onceで`index_path(day)`にGitHub Contents API `PUT`、その後`_remote_file(rel)`で**サーバから再読込**。
5. **`base64.b64decode(checked["content"]) == body.encode("utf-8")` の比較が偽**となり `FIRST_RECEIPT_INDEPENDENT_READBACK_MISMATCH`。`register`行122付近で停止。

**原因はまだ確定していない。** GitHub Contents APIが実際に読み書きしたbranch/ref、同名indexの存在・履歴・競合、反映遅延、bytes/newline/UTF-8、送信bodyと取得bodyの実SHA、既存原本と最新HEADの不整合を検査する。推測で「GitHubのバグ」「暗号鍵破損」と決め付けない。

**やってはいけないこと**：公開ログに原本平文・復号鍵を出す、旧indexを削除/上書きする、source結果が出た後に予想を再生成して同じ締切前原本と称する、読戻しを無条件スキップして`GO`にする。

## 6. SHAの不整合を見逃さない

- main `scripts/boat_main_dispatch_gate.py`の`RELEASE_SHA`固定値は `e24f09f150e2318dd16a96bdc6db1d8c1317b9ae`。
- main `.github/workflows/boat-racer-daily.yml`の`source_mirror` / 条件にもこの旧release SHAが固定されている。
- 現production branch HEADは `997535d388e8dd6609355fde6f94e90307f818a3`。
- そのため現HEADのsource実行は `HOLD_RELEASE_SHA_MISMATCH` を引き起こす可能性がある。**まず現HEADとの差分・PR #148・run #42995325741の原本とメタデータを監査してどのSHAが正本か選定**。単純な文字列置換で強引に解除せず、GitHub actual refと全CIの一致を確認。
- PR/合成CIの`success`を本番source実行の成功と数えない。

## 7. 今後の作業順序（作業が進んだ分だけ完了報告）

### P0. 既存P0原本の独立照合と保全が最優先

1. 最新のGitHub HEADとrun #42995325741、artifact ID 13842474540の保持・失効状況を再確認。7日間保持設定のため**失効前に既存恒久保存先へ安全に保存**。原本、元artifactメタ、全関連SHA、source-control/continuityは一組で保全。
2. `first_p0_bootstrap.py` の`finalize/register/_remote_file`の完全経路を、実行時のソースコミット `e24f09...`で検証。Git API ref/index bodyと読戻しの参照先を確認し、**安全なSHA・サイズ・schemaだけ**を診断に出す。
3. 新予想を作らず同じAES artifactを**別のGitHub-hosted runner**で復号・照合。JSON SHA、内包ZIP、保存時刻、予想モデル、元競走ID、結果から独立した未来時刻を確認。実証できなければ`HOLD`。
4. PR #148の旧テスト修正は別問題として慎重に確認し、必要であれば本番workerとその合格テストに最小変更を適用。古い結果や個人情報を書き換えない。

### P1. main→productionの一経路へ固定

5. main最新HEAD・production最新HEAD・選定したsource SHAを一致させ、旧固定SHAに依存した`source_mirror`条件も整合。**source-owner single writer/二重起動防止**は変更しない。
6. 既存main`boat-racer-daily.yml`の実`schedule`→`owner_p0_p1_dispatch`→既存release worker `workflow_dispatch`の発火を同一run/呼び出しIDで証明。scheduleの設定だけではダメ。
7. 新しい未来レースで実P0/P1を作る場合も、元の保存時刻が締切前、AES保存、別runner SHA一致を必須とする。

### P2. 元の照合器・表示を復旧

8. 既存 `source_mirror`→結果worker `racer_intraday_refresh`→既存結果適格性・PDCA scorerの順に、**同じrace ID・model ID・予想原本SHA**で接続。新照合器は書かない。
9. `state/boat-saved-view`の正本と`gh-pages`を比較。11/7表示を復旧済みの過去実績と区別し、11/8〜11/10や11/11の原本のない日は欠測/HOLDを残す。過去日をタイマーで今日へ飛ばさない。
10. 全レース×全現役モデル×P0/P1の予想数、`NO_FORECAST`、`HOLD`、`VOID`、公式結果認証済み数、独立SHA合格数を実物で集計。欠測をレース一覧から除外しない。

### P3. 競輪、オートレース、競馬

11. ボートの本番一巡が実証できてから競輪PR #71の既存4モデルを実データで接続。既存の個人研究用公開ページ取得は承認済みでAPI契約を全経路必須としない。ただし93必須入力の不足とB研究用候補の区別を守る。
12. オートレース・競馬も同じ受入基準、全対象レース・全現役モデルを維持する。録画・学習は初回正本の予想→照合が実証できてから既存の権限・上限内で進める。

## 8. 今後、新チャットで何をユーザーに報告するか

各回、以下を**実行IDと証拠リンク**で報告。コードを作っただけで進捗を水増ししない。

- 直近のowner-source `schedule` / `workflow_dispatch`発火実績
- 真正な未来レース対象数、モデル別予想作成数、`NO_FORECAST`数
- AES暗号artifact ID、予想原本SHA、保存時刻
- **別runner**で実読戻し合格した数・失敗理由
- 既存の公式結果と本物の予想SHAを照合したレース数・`HOLD`数
- 本番一巡実証数（現時点 **0**）
- 最も大きい障害 **1つ**と、次に行う**既存資産の修正1工程**

**新規API、別照合器、Vercel、PC運用、秘密鍵の公開、無制限GET、権限拡大は無断追加しない。**

## 9. 確認済み証拠・入口リンク

- Repo: https://github.com/haji84/RACE-AI
- BOATの既存worker: https://github.com/haji84/RACE-AI/blob/production/boat-p0-p1-20261111/.github/workflows/boat-nationwide-ab-one-shot.yml
- main本番結果＋ランチャー: https://github.com/haji84/RACE-AI/blob/main/.github/workflows/boat-racer-daily.yml
- BOAT main gate: https://github.com/haji84/RACE-AI/blob/main/scripts/boat_main_dispatch_gate.py
- PR #145 main起動・結果照合接続（統合済み）: https://github.com/haji84/RACE-AI/pull/145
- PR #148 production branch旧テスト修正（Open）: https://github.com/haji84/RACE-AI/pull/148
- PR #143 別のDraft本番経路（無断混入禁止）: https://github.com/haji84/RACE-AI/pull/143
- Run #42993305843: https://github.com/haji84/RACE-AI/actions/runs/42993305843
- Run #42995325741: https://github.com/haji84/RACE-AI/actions/runs/42995325741
- 実P0 AES artifact: https://github.com/haji84/RACE-AI/actions/runs/42995325741/artifacts/13842474540
- Main schedule run #43015122597: https://github.com/haji84/RACE-AI/actions/runs/43015122597
- 既存UI: https://haji84.github.io/RACE-AI/

## 10. 新チャットへそのまま渡す指示

> GitHub Publicリポジトリ `haji84/RACE-AI` の `docs/RACE_AI_HANDOFF_20261111.md` を読んで、最新のmain/production HEAD・Actions・既存AES原本の保存状態を取り直し、続きから実作業を進めて。最優先はBOAT run 42995325741 で実際に生成されAES保存された原本 `boat-p0-existing-42995325741` の保全と `FIRST_RECEIPT_INDEPENDENT_READBACK_MISMATCH` の根本原因修復。原本を捨てて後付け再予想しない。release SHA不一致も合わせて点検し、main→既存P0/P1→別runner SHA読戻し→既存公式結果照合→既存Pages表示を同じrace ID/model ID/SHAで一巡させて。新規照合器・新規モデルは禁止、Public/Actions/PC不要/既存AESを維持。全レース・全現役モデルを外さず、未予想はNO_FORECAST、未認証はHOLD。合成CIは完成ではない。新しい実レースの真正な予想原本と公式結果一致の証拠でのみ合格判定して。

---

**記録時の完成判定：本番一巡0件。P0候補生成14レース・28エントリ、AES artifact 1件のアップロードまで確認。独立読戻しの不一致が未解決。**
