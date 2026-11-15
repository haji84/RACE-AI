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
