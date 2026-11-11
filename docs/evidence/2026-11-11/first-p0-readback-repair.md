# BOAT first-P0読戻し修復・実原本保全の証跡（2026-11-11）

## 結論

元run **42995325741** で作成された同じAES暗号原本を保持し、回復run **43030625791** の別GitHub Actionsジョブで独立読戻しに合格した。対象原本内の **14レース・28予想エントリ・2モデル**について、原本SHA、レース・モデルの結合、実保存時刻が締切前であることを既存読取器で検証した。28エントリを28独立モデルと数えない。

**既存公式結果との一巡完了は、この記録時点では未確定。** 保全・独立読戻しの合格、CI成功、照合ジョブの技術的成功を、本番一巡合格へ読み替えない。

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
