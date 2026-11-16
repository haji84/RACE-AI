# BOAT停止復旧の修正とリリース引継ぎ（2026-11-16 JST）

本書は `RACE_AI_BOAT_CODEX_HANDOFF_20261116.md` のG1を継続した記録。
**承認後にPR #302/#289を適用し、新P0/P1保存を実証。独立した新P1 AES・連続無人引継ぎ・画面受入は検証中。**
最新の件数と失敗は [最新状況](RACE_AI_LATEST_STATUS.md) 冒頭と末尾の追記を参照。
以下は障害調査開始時点の記録を保全する。新規PRは作らない。

## 再取得した正本

main `96e0045ffb3a8368c4f63cb955564bb4e6259c0e`、production
`5d1dabff0ab9bb83132cd7fbdd43f49fb4eef6c4`、PR #302の開始HEAD
`a5d19e8f8b70eaacd9c5841bc95f5cbbb2e8b145`。

- 失敗owner: https://github.com/haji84/RACE-AI/actions/runs/43683174565
- 復旧失敗: https://github.com/haji84/RACE-AI/actions/runs/43716692197
- 引継ぎ元owner: https://github.com/haji84/RACE-AI/actions/runs/43661420983

失敗ownerのALL_MODEL・source-control・continuity、および前ownerのsummary・continuityの
5 ZIPを再取得し、GitHubメタデータのサイズ・SHA256と一致確認した。
このホストにはAES鍵がなく、復号・別runner認証を完了したとは扱わない。

## 確認した原因と修正

1. zero-round復旧が、当該workerのGET0だけでなく一日全体のGET0を要求していた。
   前workerの452件を引継ぐ実障害では累積11524・当日基点11072・巡回累積608・
   失敗worker使用0。この正当な継続を拒否した。新条件は基点≦累積を認め、
   当該worker使用0、署名済みsource-controlとの完全一致、原本在庫・受領証、
   待機/停止なしの検証を維持する。カウンタをゼロへ書き換えない。
2. prepared-round復旧に古い240 GET制限が残っていた。既存の上限撤去方針と整合させ、
   カウンタの順序・型・署名済みP1/RESULTペアとの一致・403/429時のHOLDは維持した。
3. VaultのGit設定引数 `-c` によりfetch判定が外れ、既存の180秒ではなく60秒が適用された。
   実際のサブコマンドを判定し、リモート書換え拒否と既存180秒を適用する。
   タイムアウトは操作別の固定コードのみ出力し、引数・通信本文・秘密は出さない。
4. mainの独立したproof消費器にもzero-round分岐が不足していた。
   修正済みproofをproductionが出してもmainが拒否するため、既存PR #289で同期する。

実障害のdisplay feedは180秒タイムアウトを2回記録し、その後Vault保存が約64秒で失敗した。
Vaultの内側の失敗操作は旧ログにないため、3を唯一の歴史的原因とは断定しない。
修正後の新しい一時bare repositoryからの鍵不要・blobなし読取りは1.808秒で成功したが、
これはAES読戻し・書込み成功の証明ではない。

## 検証の範囲

- 失敗を再現した回帰テストを追加し、既存owner全385件、復旧/Vault全179件、
  サイトNode15件、main消費器関連55件成功。範囲は重複しており合算しない。
- 独立レビューでカウンタ境界・偽造proof・Gitタイムアウト・秘密非出力を確認。
- 実障害の取得済みZIPを使う歴史時刻での再現は成功。現在のdispatch許可として使わない。
- 公式providerへの新規GET0、新規予想0、既存原本変更0。本番の再開成功を意味しない。

詳細は [件数・SHA証拠](evidence/boat-zero-round-recovery-validation-20261116.json)。
個別CIは既存PR #302の厳密HEADのChecksを正とし、別HEADの緑を流用しない。

## リリースと未完ゲート

本人の従来の「main統合・本番切替を無断実施しない」に従い、まだproduction/mainは変更しない。
本番更新には、レビュー済みPR #302の統合後の**実際のproduction HEAD**を確定し、
既存PR #289のowner発火・復旧・mirror・独立readerの厳密固定SHAを同期する必要がある。
旧原本を再監査するSHAは、既知の履歴用読取りとして別に保持する。
mainのSHAチェック撤去、GitHubイベント偽装、secretジョブの手動迂回は行わない。

G1はコード/ローカル試験合格で、本番の「実AES復旧→別runner→新P1保存」待ち。
G2の真正な締切延長、G3の日付跨ぎ、G4/G5の全国適格分母と全14モデル照合、
G6の新結果→PDCA→Pages、G7の3〜6艇映像、G8の連続運用・未来精度も
それぞれ実データ合格待ち。過去の9モデル枠の締切不一致HOLDは変更しない。
98%は未達・実現可能性未証明。旧ローカル常駐処理の再起動や原本再生成で補わない。


## main側の修正と実HEAD固定（既存PR #289）

main `96e0045ff...` を既存PR #289の `b754c8a01...` へ競合なく取り込み、
既存の05:30 JST早期起動を保全。zero-round proofの消費器もproductionと同一にした。
6ファイル・22箇所のlive固定SHAをレビュー済み候補
`0db526870a509cd6e68c44e693ed3e73d3b0e50f` に結合した。
**これはリハーサル用。現在のproductionは5d1dabffのままなので、mainへ統合してはならない。**

独立readerはrunの認証済みSHAと、P0・ALL_MODELの受領証・元予想のsource SHAを一致させる。
旧 `5d1dabff...` は読取り専用監査だけで許可し、dispatchの固定SHAへは追加しない。
既存の特定historical run 43348227701/0796b52cの読取りも維持。

失敗owner 43683174565は最初のP0を再利用したため、同runのfirst-P0を必要とする通常監査を
そのまま適用できない。既存matrix workflowの**main push時の既存認証job内**に、
source-control/continuityのZIP・SHA・AESと全公開counterの一致を現在時刻で読む処理を追加した。
別のdispatch proofは作らず、履歴の監査が成功しても新ownerの取得許可は与えない。
新job/workflow/手動secret入力/公式provider GETは追加しない。

main gate 74件、matrix/exact/failed-checkpointの独立package試験37件成功。
後者には本物のAES暗号を使う架空の6試験（サブケースあり）を含む。
実鍵での過去障害原本の別runner成功はまだ未実行である。

### 本人承認後の順序

1. PR #302が0db526870のままでCI3系統成功、productionに未レビュー差分がないことを再取得。
2. PR #302を既存の保護ルールに従ってproductionへ統合し、GitHubから新しい実HEADを取得する。
3. 既存PR #289の22箇所と3スクリプトのactive定数をその**実HEAD**へ再結合。
   既知の旧原本SHAは履歴専用のまま。mainの新しいHEADで74/37と既存CIを再検証。
4. PR #289をmainへ統合し、真正なschedule・workflow_runと既存workflowを利用して一writerを確認。
   新レースが対象になる前に、復旧・counter・拒否/待機・原本引継ぎを確認する。
5. 別runnerの失敗checkpoint AES監査と、新しいP0/P1・GitHub物理保存時刻・公式結果・Pagesを
   同一run/race/modelで照合。HOLD・欠落と不明を記録し、G1〜G8の未達を勝手に合格にしない。

[main準備証拠](evidence/boat-main-zero-round-release-preparation-20261116.json)。
CI本番producer skippedと本番未更新を、現在の未予想0件と取り違えない。


main側のコードHEAD `80b3b81f7ddb8e79a7d6f751d621043022ae7fbe` で全12チェック成功。
BOAT復旧gate69件（run43770742038）、独立原本37件（run43770742073）、
mirror205/30件・結果31件・起動44件（run43770742201）が成功した。範囲は重複する。
本番AES監査とproducer/dispatcherはPRではskippedで、本番再開成功には数えない。
この後継の記録更新はdocsのみ。productionは5d1dabff、mainは96e0045ffのまま。


## 承認後の本番統合（2026-11-16 JST）

本人の「承認する」を受領し、PR #302を保護ルールの通常mergeで統合した。
実production HEAD `84128e0ec8bd9fe3da64ad49f74b8511b07e72be` のtreeはレビュー済み0db526870と完全一致。
PR #289のlive固定SHA22箇所をこの実HEADへ同期し、ローカル74/37件成功。
既知の旧5d1dabffはread-only監査にのみ保持し、dispatcherの許可へ追加しない。
mainの最終CI→通常merge→別runnerの実AES→真の新owner保存を続けて実行する。
本書の以前の「承認待ち・production未変更」はその記録時点の履歴である。
[承認後の正本証拠](evidence/boat-owner-approved-release-20261116.json)を参照。


## 実運転再開と受入の更新

PR302/289は本人承認後にproduction84128e0/mainEA8965へ統合済み。
実障害のAES/counter独立読戻しはrun43772458812で合格。
新owner43772481781が自動起動し、P0恒久保存とP1暗号ZIPの物理保存を確認した。
新しい原本の全件数・締切・AESは、別runnerの完了イベント監査へ続ける。
受入43778358422は結果更新が一部成功、画面は汎用BROWSER_CHECK_FAILEDで未合格。
既存PR286でcollectorと読取版を同期し、実画面を再試験する。source84128は稼働を継続。
[最新の件数・SHA・未完条件](evidence/boat-approved-restart-live-20261116.json)を参照。
