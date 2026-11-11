# BOAT first-P0読戻し修復・実原本保全の証跡（2026-11-11）

## 結論

元run **42995325741** で作成された同じAES暗号原本を保持し、回復run **43030625791** の別GitHub Actionsジョブで独立読戻しに合格した。対象原本内の **14レース・28予想エントリ・2モデル**について、原本SHA、レース・モデルの結合、実保存時刻が締切前であることを既存読取器で検証した。28エントリを28独立モデルと数えない。

最新のrun **43038009675** では、同じ元原本を保存済み公式結果14レースと照合し、**13レース・26予想を採点、HIT6・MISS20、1レース・2予想の異常状態HOLDを維持**した。表示名は延べ84出走枠すべてが検証済み名簿に結び付き、既存Pagesの実ブラウザ検査も `LIVE_OWNER_SITE_VERIFIED` となった。後続dailyと4日分のAES読戻しも成功。ただし後続処理の別集計で元P0のHOLDを解除せず、全履歴完了とは判定しない。CI成功を実原本・実画面の証拠の代わりにはしない。

## 原因の確定範囲と修復

実行時ソースは [`e24f09f150e2318dd16a96bdc6db1d8c1317b9ae`](https://github.com/haji84/RACE-AI/blob/e24f09f150e2318dd16a96bdc6db1d8c1317b9ae/scripts/first_p0_bootstrap.py)。`register` はContents APIの作成成功レスポンスに含まれるコミットSHAを利用せず、直前に不存在を確認した可変ブランチを再読込していた。不存在と内容不一致のどちらも `FIRST_RECEIPT_INDEPENDENT_READBACK_MISMATCH` になり、停止時のGETレスポンスは記録されていなかった。

一方、receiptは失敗前にコミット [`20fc291429003fd0351baef4b0c1918b76b4e066`](https://github.com/haji84/RACE-AI/commit/20fc291429003fd0351baef4b0c1918b76b4e066) で実際に作成されている。440 bytesの保存内容は元のJSON直列化と一致し、今回の独立読戻しでも同じ本文SHA・blob SHAを確認した。元コードのPUTとGETは同じreceiptブランチを参照しており、productionとのブランチ名の違いだけで今回の不一致を説明することはできない。

**確定したコード上の問題は、作成コミットへ固定しない読戻し。** 古い不存在応答や反映遅延は有力な可能性だが、失敗したGETの実体が残っていないため、HTTP 404、キャッシュ原因、GitHub障害のいずれも断定しない。

修復では、作成レスポンスのコミットSHA、ファイルパス、種類、サイズ、blob SHAを検証し、**その作成コミットを指定して独立GET**する。既存receiptは一致確認後に再利用し、上書きしない。実際の不一致は引き続き停止する。予想の再生成、読戻しの省略、無条件リトライは追加していない。

## 実原本の保全・独立読戻し

| 工程 | 実行証跡 | 確認結果 |
|---|---|---|
| 元P0生成・AES保存 | [元run 42995325741](https://github.com/haji84/RACE-AI/actions/runs/42995325741) | artifact `13842474540`。生成ソースは `e24f09f150e2318dd16a96bdc6db1d8c1317b9ae` |
| 既存暗号保管先への保全 | [retention job 130556414410](https://github.com/haji84/RACE-AI/actions/runs/43030625791/job/130556414410) | success。P0、CONTINUITY、SOURCE_CONTROLの3原本を保全 |
| 別runnerの独立読戻し | [readback job 130556929586](https://github.com/haji84/RACE-AI/actions/runs/43030625791/job/130556929586) | success。14レース・28エントリ・2モデル。締切前検証は14レース・28エントリ |
| 既存経路での結果照合 | [reconcile job 130557105782](https://github.com/haji84/RACE-AI/actions/runs/43030625791/job/130557105782) | ジョブはsuccess。ただし、この実行では公式結果認証済み0件、HOLD 28エントリ |

保全コミットは [`2448b33de6ecf7388f8fd8577860622b67b9b9a2`](https://github.com/haji84/RACE-AI/commit/2448b33de6ecf7388f8fd8577860622b67b9b9a2)、親は `24fb32c3011bac14c58031bf77df1c88ae86c520`。Actions artifactの保持期限とは別に、既存Git保管先へ暗号原本と元receiptを保持し、別runnerからこのコミットを指定して復元した。

同じ元runの継続原本 `13842779131` とソース制御原本 `13842973909` も照合し、元run・ソースHEAD・暗号文の結合を既存検証処理で確認した。回復処理での新予想作成は0、外部レース情報取得は0、平文公開はfalse。保存時刻は元artifactの **2026-11-11T09:29:52Z** を使用し、回復時刻へ置き換えていない。

確認用レポート：

- [first-p0-retention-43030625791.json](first-p0-retention-43030625791.json)
- [first-p0-independent-readback-43030625791.json](first-p0-independent-readback-43030625791.json)
- [回復runの安全な集計artifact 13860447747](https://github.com/haji84/RACE-AI/actions/runs/43030625791/artifacts/13860447747)

## 変更していない原本識別子

| 対象 | SHA |
|---|---|
| 予想JSON SHA256 | `9073715a51b145efe77b612d4a9fd4ec2739e8c617ee3840b7751c30769ad1b4` |
| GitHub artifact ZIP SHA256 | `8e9d92d2bfd9b2f73db881bd07619747c3498a647f6175ef7be56b56c8868d78` |
| AES暗号文 SHA256 | `f4df5195e7376dce82550c8f54354bf49cf2a661bd3956b4e6fe8020c9ff390d` |
| 内包ZIP SHA256 | `6dd78cac4469f93dde29bd29817d3dfc79c53d782fb42c687ab32ac65ab096ba` |
| receipt本文 SHA256 | `749980a6cfa62f6588b938a254b887940cd54092d22a388d8d96516d05aa5161` |
| receipt Git blob SHA | `147a7ff6ed13ea1f167daf0cc99c2a480322c7eb` |

[元receiptの固定コミット版](https://github.com/haji84/RACE-AI/blob/20fc291429003fd0351baef4b0c1918b76b4e066/docs/evidence/2026-11-11/p0-first-receipt.json) は変更していない。予想本文、個別モデルID、秘密鍵は本書へ掲載しない。

## 修復コードと検証の位置づけ

- production修復コミット：[`a60b8493ee67f8cf1006d3c240ffd121a5f359ce`](https://github.com/haji84/RACE-AI/commit/a60b8493ee67f8cf1006d3c240ffd121a5f359ce)。親は `997535d388e8dd6609355fde6f94e90307f818a3`。
- main統合：[PR #152](https://github.com/haji84/RACE-AI/pull/152)、マージコミット [`01d08260aa0c8a47217df88abdfa64c16c3c9e80`](https://github.com/haji84/RACE-AI/commit/01d08260aa0c8a47217df88abdfa64c16c3c9e80)。
- production CI：[run 43030076250](https://github.com/haji84/RACE-AI/actions/runs/43030076250)、130件合格。
- main CI：[run 43030338255](https://github.com/haji84/RACE-AI/actions/runs/43030338255)、146件と20件の検証群が合格。main側の追加ローカル検証23件も合格。

これらは変更コードの検証結果。実原本の保全・読戻しの証拠は上記回復runの実ジョブであり、公式結果との一巡合格判定とは分ける。既存モデル、既存照合器、AES形式を継続し、今回の原本を後付けで予想し直していない。

## 公式結果の補充と独立再照合

回復runの最初の照合では、保存済み公式結果に今回の対象レースの記録がなかったため、公式結果認証済み0件、HOLD 28エントリを維持した。[初回照合レポート](first-p0-reconciliation-43030625791.json) を保存し、このHOLDを削除していない。

原本の復旧後、既存の結果収集run 43015122597のdailyジョブだけを再実行した。P0/P1生成担当は起動せず、既存コード914941a6244364480370ac392441ad4bb5781f83、1回12リクエストの上限、公式取得・認証・暗号保存を維持した。

- [attempt 2、job 130558875133](https://github.com/haji84/RACE-AI/actions/runs/43015122597/job/130558875133)：12リクエスト。照合用feedの結果待ちは7レース。結果保存generation 62。[レポート](first-p0-result-collector-43015122597-attempt-2.json)
- [attempt 3、job 130561674999](https://github.com/haji84/RACE-AI/actions/runs/43015122597/job/130561674999)：12リクエスト。照合用feedの結果待ちは0レース。結果保存generation 63、commit e95d01b35f96cafff9d0313db80e2eb7ab647cac。[レポート](first-p0-result-collector-43015122597-attempt-3.json)

上記feedの対象146レースには以前の日の原本も含まれる。145確定・1HOLDという全体件数を、今回の14レース・28予想の採点件数へ転用しない。元P0だけを対象とする独立再照合と、既存Pagesの明示P0検証で最終判定する。新しいP1原本や全日・全競技の完了は、この記録では証明していない。

## 追加実測：元P0の採点と表示名接続の修復

[run43034336347](https://github.com/haji84/RACE-AI/actions/runs/43034336347) では、同じ保全コミットの原本に対し、公式結果14レースを使用し、13レース・26予想を採点した。HIT6、MISS20、通常完走以外の状態を含む1レース・2予想は `ABNORMAL_FINISH_REVIEW_REQUIRED` として残した。予想原本とネイティブ採点SHAを別の監査担当も照合した。

- [この実行の独立読戻し報告](first-p0-independent-readback-43034336347.json)
- [元P0に限定した採点報告](first-p0-reconciliation-43034336347.json)

実ブラウザは名前の未取得表示を拒否した。P0のnative投影が登録番号だけを作り、復旧wrapperが既存の認証済み表示名補充を呼んでいなかった。予想の不一致ではない。ブラウザ条件は変更せず、保存済みruntime・既存TERM reader・既存mergerを接続する修正をproduction ba2d2d698b90548dd67b6ca7ac2dada776b09e32 に追加した。別日データ、元予想辞書、原本SHA、採点結果を変えないことを実AES/Git/TERM検証で確認している。更新後の実データ検証は次節に記録する。

## 最新実測：名前接続後の元P0照合と実Pages検証

[PR #154](https://github.com/haji84/RACE-AI/pull/154) のmain統合コミットは [`15047c84de0b44126dc97f85ca5ff0b66bb7eeab`](https://github.com/haji84/RACE-AI/commit/15047c84de0b44126dc97f85ca5ff0b66bb7eeab)、実行productionは [`ba2d2d698b90548dd67b6ca7ac2dada776b09e32`](https://github.com/haji84/RACE-AI/commit/ba2d2d698b90548dd67b6ca7ac2dada776b09e32)。[run43038009675](https://github.com/haji84/RACE-AI/actions/runs/43038009675) で既存原本の回復経路を再実行した。元の生成ソース `e24f09f150e2318dd16a96bdc6db1d8c1317b9ae` と今回の修復実行ソースを混同しない。

| 工程 | 実ジョブ | 確認結果 |
|---|---|---|
| 元原本の保全確認 | [130581941861](https://github.com/haji84/RACE-AI/actions/runs/43038009675/job/130581941861) | runner `1000042267`、success。既存vault commit `2448b33de6ecf7388f8fd8577860622b67b9b9a2` を維持 |
| 別runnerの独立読戻し | [130582152757](https://github.com/haji84/RACE-AI/actions/runs/43038009675/job/130582152757) | runner `1000042268`、success。14レース・28予想・2モデル、締切前保存14レース・28予想 |
| 既存の公式照合 | [130582378667](https://github.com/haji84/RACE-AI/actions/runs/43038009675/job/130582378667) | 公式結果14レース、13レース・26予想を採点。HIT6、MISS20、異常状態HOLD2 |
| 表示名の補充 | 同ジョブの照合レポート | 延べ84出走枠中、名前あり84、認証済み名簿への結合84、欠損0 |
| 既存Pagesの実ブラウザ検証 | 同ジョブstep10 | `2026-11-11T14:26:20.661Z`、`LIVE_OWNER_SITE_VERIFIED` |

名前は固定runtime commit `a2f020f00e6e7309546c13f16a776d9d2f53a931` の既存TERM原資料から読み、原資料SHAは `5c1e21cfe5a4dd53ea26eb07aca4905c4c20c3160b4a206ba96e92702eb4b46d`。84は延べ出走枠数で、異なる選手の人数ではない。名前を予想入力・買い目・採点へ反映していない。原本文書集合SHAと採点SHAは前回run43034336347と一致し、採点SHAは `e8a142ca13b1b968b2958b4ee49c78ff54037f3d3fbddb49769ec4a954bafedb`。新予想作成0、予想書換え0、復旧処理からの公式情報取得0。

実Pages検査時の表示feedはgeneration `115`、commit [`439b697b1df95d19c82ab3ae9df6f05eab9ca6fc`](https://github.com/haji84/RACE-AI/commit/439b697b1df95d19c82ab3ae9df6f05eab9ca6fc)。既存Pagesを11/11・明示stage P0で開き、artifact ID・原本JSON SHA・元コードコミットへ固定した対象と実表示を照合した。`expected_original_matched`、`native_original_audit_verified`、`native_p0_detail_visible`、`participant_names` はtrue。P0モデル群2、表示結果14を確認した。

実ブラウザ検査は幅320・390・1440の3種類で行い、モデル切替3画面・原本検査6件を確認した。28枚全カードを個別検査したという意味ではない。`key_in_requests_or_storage=false`、`official_source_requests=0`、`plaintext_published=false`。この検査時点はすでに締切後で、`future_native_visible_before_cutoff=false`。未来レースを締切前に実画面で観測した証拠には数えず、元原本の締切前保存14レース・28予想の独立証跡と分ける。

今回の照合レポートのstatusは `HOLD_OFFICIAL_RESULTS_INCOMPLETE` のまま。これは1レース・2予想が `ABNORMAL_FINISH_REVIEW_REQUIRED` であるためで、14レースの公式結果が未取得という意味ではない。初回の「結果なし・HOLD28」と今回の「公式結果あり・異常状態HOLD2」は別の状態として履歴を保持する。

- [元原本の独立読戻しレポート](first-p0-independent-readback-43038009675.json)
- [元P0の公式照合・表示名の安全レポート](first-p0-reconciliation-43038009675.json)
- [実Pages検証の安全レポート](first-p0-pages-43038009675.json)
- [対象原本を固定した検査コンテキスト集計](first-p0-site-context-counts-43038009675.json)

### 後続dailyの確認

[job130583568151](https://github.com/haji84/RACE-AI/actions/runs/43038009675/job/130583568151)、runner `1000042271` はsuccess。run全体は `2026-11-11T14:27:53Z` にcompleted success。既存 `verify_all_history_pdca_readback` は4日分のAES readback coverageをtrueとしたが、`all_history_completion_proven=false` を維持している。

同処理の11/11集計は14レース・28予想・eligible28・HIT6・MISS22・unresolved0。各モデルでは14eligible・HIT3・MISS11だった。一方、今回の原本照合結果の正本であるnative評価は13レース・26予想採点・HIT6・MISS20・異常HOLD2を維持した。

差の所在は実ログと既存コードで確認できた。元P0の [`frozen_day_cycle.settle`](https://github.com/haji84/RACE-AI/blob/ba2d2d698b90548dd67b6ca7ac2dada776b09e32/race_ai/frozen_day_cycle.py) は照合対象の出走者に `finish_status != FINISHED` があれば `ABNORMAL_FINISH_REVIEW_REQUIRED` とする。日次の[既存投影](https://github.com/haji84/RACE-AI/blob/ba2d2d698b90548dd67b6ca7ac2dada776b09e32/race_ai/private_cycle_projection.py)と [`retained_model_pdca_audit`](https://github.com/haji84/RACE-AI/blob/ba2d2d698b90548dd67b6ca7ac2dada776b09e32/race_ai/retained_model_pdca_audit.py) は、認証済みの入賞者・着順・公式払戻・返還条件を既存bulk採点へ渡し、全出走者の通常完走を同じ条件としては要求しない。判定部分は修復前 `997535d388e8dd6609355fde6f94e90307f818a3` から変わっていない。

名前修正がHOLDを解除したのではなく、既存処理の規則差による別集計である。判定の統一や元P0のHOLD解除は実施していない。dailyのunresolved0を使ってHOLD2を消したり、元P0の28予想すべてを採点済みと報告したりしない。全体ledgerの未完了54レース・未採点498予想も今回の原本28予想とは別の分母で、全履歴完了は未実証である。

- [後続daily・履歴読戻しの安全な集計](first-p0-historical-readback-counts-43038009675.json)
- [今回の実証全体と限界をまとめた固定証跡](first-p0-production-proof-43038009675.json)

### 次の実地確認

既存の翌朝P0/P1起動枠の実発火を確認し、次の真正な原本の新規receipt PUTで、応答コミットを指定した独立GETが成功することを実環境で証明する。今回の回復は作成済みreceiptを再利用した。新規PUT経路は回帰テストで検証したが、今回の回復runはその実地証明ではない。定期設定が残っていることを翌朝の完走保証へ読み替えない。

今回のP1原本は元run停止前に生成されておらず、後付けでは作らない。次の未来レースでの定期発火・P0/P1完走や、全日・全競技・全現役モデルの完成は今回の証拠範囲に含まれない。
