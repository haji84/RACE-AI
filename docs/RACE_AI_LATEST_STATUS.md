<!-- RACE_AI_BOAT_LIVE_RESTART_20261116 -->
# 2026-11-16 JST｜承認済み本番復旧：新P0/P1の自動保存を確認

- **本番適用済み:** PR #302をproduction `84128e0ec8bd9fe3da64ad49f74b8511b07e72be`、
  PR #289をmain `ea8965bd49955f5d1e204ca318cf9c542352f345` へ通常merge。いずれもレビュー済みtreeと一致。
  このチャットで本人承認を受領済み。
- **実障害原本の独立AES合格:** main run43772458812/artifact14185455502で、停止したowner43683174565の
  AESと公開counterが一致。累積11524・当日引継ぎ452・失敗worker取得0・巡回累積608を保全。
- **自動実行を再開:** main起動43772458763からowner43772481781を一writerで開始。
  前回失敗した追加P0の恒久保存が今回は成功。08:20:46 JSTに通常P1、08:24:08に全モデル側P1の
  新しい暗号ZIPを確認し、GitHub SHA/サイズを再検証した。
  新P1の全件数・独立AES・公式締切照合は、完了イベントの別runnerで引き続き確認する。
- **結果更新は一部成功、画面は未合格:** 既存受入run43778358422は結果更新が成功し、
  選択済み2日分で9レースを変更、確定149・保留9・未確定118を報告（当日だけの数ではない）。
  表示context世代314は生成できたが、ブラウザは `SAVED_SITE_BROWSER_CHECK_FAILED`。
  旧readerの診断が不足しており、原因を断定しない。
- **既存PR #286で修正・再検証:** 旧12件固定を残すcollector呼出しを検証済みb47へ更新。
  通常のP1画面確認を承認済みproducerと同じ84128のreaderへ合わせ、過去P0専用0796は保全。
  ローカル74/37/31件と独立レビュー合格。次は同HEAD CI・main適用・実画面再試験。
  稼働中producer、job数、権限、スケジュール、モデル係数は変えない。

新規PR/Issue/workflow/モデル系統/課金・投票・原本改変は0。
G2〜G8、映像3〜6艇、前向き精度改善・98%は未合格。以下は以前の記録として保存する。
[件数・SHA・失敗を含む今回の証拠](evidence/boat-approved-restart-live-20261116.json)。
<!-- /RACE_AI_BOAT_LIVE_RESTART_20261116 -->

<!-- RACE_AI_BOAT_OWNER_APPROVED_RELEASE_20261116 -->
# 2026-11-16 JST｜本人承認済み：BOAT本番復旧リリース

本人がこのチャットで「承認する」と回答。既存PR #302のproduction統合、実HEADへ同期した
既存PR #289のmain統合、自動予想の再開・独立読戻しが承認された。
追加の確認待ちではない。無断の一般公開・モデル係数切替・新規課金・投票は含まない。

- **production統合済み:** PR #302、実HEAD `84128e0ec8bd9fe3da64ad49f74b8511b07e72be`。
  GitHubから読戻し、レビュー済み0db526870とtreeが完全一致することを確認。
- **mainの固定SHAを同期済み:** 6ファイル22箇所を上記実HEADへ変更。
  履歴原本の読取専用5d1dabffは保全。ローカルmain gate74件、独立AES reader37件成功。
  実HEAD同期後のCIも成功。既存のmain release push起動経路で最初のworkerを開始し、
  main統合・真正な別runner実行・新しい予想保存を続けて確認する。
- **未実証:** 実障害のAES復旧→新worker→新P1保存、全レース/モデルの連続完走、
  新結果→PDCA→画面の一巡、映像・精度改善。合成試験を実レース成功へ数えない。
- **保全:** 原本変更0、新PR/Issue/workflow/外部サービス/課金0。旧PC常駐monitorの再起動なし。

[承認後リリース証拠](evidence/boat-owner-approved-release-20261116.json) /
[既存PR #289の最新Checks](https://github.com/haji84/RACE-AI/pull/289/checks)。
以下は承認前の検証記録であり、そこでの「承認が必要」は過去の状態。
<!-- /RACE_AI_BOAT_OWNER_APPROVED_RELEASE_20261116 -->

# RACE-AI 最新状況（2026-11-16 JST）

BOAT最終引継ぎのG1を優先し、実障害の原本調査からコード修正まで進めた。
**本番の新予想再開・映像完成・98%達成は、まだ宣言できない。**

## 完了した作業

- 既存PR #302のHEAD `0db526870a509cd6e68c44e693ed3e73d3b0e50f` に、
  当日使用量を引継ぐzero-round復旧、巡回途中に残った旧240件制限の撤去、
  VaultのGit fetch判定と秘密を出さないタイムアウトを実装した。
- 同HEADでGitHub CI3系統成功。owner324/46/3/12件、復旧140件、Vault75件成功。
  範囲に重複あり。本番producerはPR上でskipped。
- 既存PR #289へmainの最新96e0045ffを取り込み、05:30 JST早期起動を保全。
  mainのzero-round受理不足を修正し、本番固定SHA22箇所を候補へ同期した。
- 過去原本の再検証は実runのSHAと受領証・予想のsource SHAを厳密照合する。
  失敗runのAES checkpoint専用読取も既存監査jobに接続。main gate74件、
  独立したmatrix/exact/failed-AES37件のローカル試験成功。実鍵の監査はまだ未実行。
- PR289コードHEAD `80b3b81f7ddb8e79a7d6f751d621043022ae7fbe` でもGitHub全12チェック成功。
  [復旧gate69件](https://github.com/haji84/RACE-AI/actions/runs/43770742038)、
  [独立原本読取37件](https://github.com/haji84/RACE-AI/actions/runs/43770742073)、
  [既存mirror205/30件・結果31件・起動44件](https://github.com/haji84/RACE-AI/actions/runs/43770742201)が成功。
  範囲は重複する。本番のAES・取得・dispatch jobはPR上でskipped。
- 実障害と前workerの5 ZIPのGitHub SHA・サイズを再検証し、使用量11524/11072/0、
  巡回累積608を保全。歴史時刻での再現は現在のdispatch許可にはしない。

## 未完条件

| Gate | 現在の状態 | 残る実証 |
| --- | --- | --- |
| G1 | コード・PR302 CI合格、本番HOLD | 真正な別runner AES復旧→次worker→新P1物理保存 |
| G2 | 既存PR302の検証処理あり | 真正な締切短縮/延長と実保存の独立照合 |
| G3 | 早朝起動のコード・ローカル試験合格 | 日付handoff・初レース欠落なし・継続実運転 |
| G4/G5 | 過去原本の一部監査あり | 新しい全国適格race×model分母と全P0/P1の独立AES照合 |
| G6 | 既存原本の表示実証あり | 新公式結果→PDCA→Pages→実画面の全件一巡 |
| G7 | 研究継続、実データ合格待ち | 3〜6艇の継続識別・動作の強さ・締切前映像P1 |
| G8 | 未合格 | 複数開催日の連続運用、未予想率、未来A/B精度改善 |

過去の締切不一致9モデル枠はHOLDを維持。98%は未達・実現可能性未証明。
この作業で公式provider GET0、新規予想0だが、当日全体の実績が0という意味ではない。
未取得の最新全件数は不明として扱う。

## 本人承認が必要な工程

productionは `5d1dabff0ab9bb83132cd7fbdd43f49fb4eef6c4`、mainは
`96e0045ffb3a8368c4f63cb955564bb4e6259c0e` のまま。
従来の無断main統合・本番切替禁止、および正式引継ぎ§6に従い、まだ更新していない。
PR302統合後の**実production HEAD**を取得し、PR289の固定SHAを再結合・同HEADでCI確認後に
mainへ統合する必要がある。現在のPR289の候補SHAをそのままmainへ入れてはならない。

新規PR/Issue/workflow/課金・一般公開・投票・予想原本改変なし。
旧ローカル常駐monitorは再起動しない。

[詳細・リリース順序](RACE_AI_BOAT_RECOVERY_20261116.md) /
[件数・原本/テストSHA証拠](evidence/boat-main-zero-round-release-preparation-20261116.json)
