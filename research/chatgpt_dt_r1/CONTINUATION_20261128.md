# DT-R1 継続実行と実証の状態

更新: 2026-11-28 JST。旧引継ぎにある未保存・未復号・Draftの状態を、以下の実行証拠で更新する。完了した学習や保存を繰り返さない。

## 閉じた工程

### P0: 学習bundleの恒久保存、独立読戻し、所有者鍵での復元

- 元run 46049489264の12ファイルを、その外部固定manifest SHAと全バイトSHAを照合して、既存の `state/keirin-encrypted-history` に追加保存した。state commit `410596da678beddcef6f8ca645cdc4e970f2d0fb`。既存1798ファイルを保持した。
- 別GitHub runner [46076680144](https://github.com/haji84/RACE-AI/actions/runs/46076680144) で12ファイルを読み戻した。実owner鍵の検証はこの段階では未実施だった。
- 関連PR #408を、required `unit` と対象CI成功、独立レビューを経て通常マージした。main commit `20db6dafe466eb4be6dd171db8f83b9de3ffb54a`。main保護、既存secretの範囲、source gate、スケジュール、本番モデルpinは変えていない。
- 既存 `keirin-result-live.yml` のmain限定・手動 `dt-r1-restore` を実行。[run 46080603797](https://github.com/haji84/RACE-AI/actions/runs/46080603797)、job `140779451567` は成功。2026-11-28 08:10:23 JSTに `OWNER_MODELS_RESTORED_AND_VERIFIED` を確認。
- DT-R1本体の24研究ファイルと7固定点数の校正、B候補の2ファイル、Codex凍結モデルを、既存owner鍵で復元・検証した。一時平文は削除され、公開出力は許可した集計とSHAだけ。新規学習0、予測0、提供元への取得0、本番昇格なし。

証拠: [retention.json](evidence/20261128-continuation/retention.json)、[independent-ciphertext-readback.json](evidence/20261128-continuation/independent-ciphertext-readback.json)、[owner-model-restore.json](evidence/20261128-continuation/owner-model-restore.json)。元の外部manifest SHAは `497154664f90725024836fbfe7cc84def152ccadb13868ccae0edb7b14c8cc4f`、DTモデル内部SHAは `5e022092a35c0258954090c6f3d0f8fa14f03f22511b28d6aa9183f5a38c381c`。

### B候補: 実学習した重みを保持して実復元

元pilotの重みが残っていなかったため、保存工程を完成させる1回だけのfitを実施した。失われた重みの完全復元や、新しい精度実験とは呼ばない。

- [run 46078387927](https://github.com/haji84/RACE-AI/actions/runs/46078387927)、source commit `418130cc11993615f21545ad370e2c726c056ea5`。共通fit20,041レース、3最適化とも収束。final testを開いていない。
- tuneは登録2416、採点可能2393。直接モデル→B混合の三連単1点は275→278、二車単1点は553→564、top3 Log Lossは4.1797597827→4.1525927148。既参照期間での結果であり、独立した未来改善の証明ではない。
- 外部manifest SHA `36952b78e652c0c5acb74ca6aeb38f882b3e8bab77121dee6071f50c9f2c8682`。state commit `b33be58a4b0920003f40fd75157ecbd79272c9ad` へ2ファイルを追加し、従前1810ファイルを保持した。
- 別runner [46080045742](https://github.com/haji84/RACE-AI/actions/runs/46080045742)、job `140776667698` で2ファイルと12推論・学習source pinを検証。さらに上記owner復元runで復号・モデル整合も検証した。

証拠: [back-study.json](evidence/20261128-continuation/back-study.json)、[back-retention.json](evidence/20261128-continuation/back-retention.json)、[independent-back-ciphertext-readback.json](evidence/20261128-continuation/independent-back-ciphertext-readback.json)。この保存済み候補を再学習して置換しない。

## 重複実行しなかった後続期間の検証

別の並行更新にあった [run 46077103288](https://github.com/haji84/RACE-AI/actions/runs/46077103288) を読み戻し、再実行しなかった。11月23〜26日の登録329・共通採点326で、初期版→凍結5機能版は三連単1点36→40、2点64→70、4点111→109、9点158→156、12点173→171、二車単1点76→79、2点124→125。良化と悪化の両方がある。モデル作成より前のレースなので未来検証ではなく、3者対戦でもない。

## 未来レースの経路

`official_inputs.py` は保存済み公式card/profileを既存の独立source受付で再検証し、公式登録番号と実時計を用いてDT入力を作る。過去アーカイブの複合IDを公式IDへ推測結合しない。現時点の履歴欠測、映像欠測、気象欠測は保持する。462列の推論には、学習時と同じ固定会場sidecarと推論source SHAを要求する。

既存 `keirin-result-live.yml` のmain・手動・同一権限内に、DT単独の未来shadowと別runの暗号文readbackを接続する。公式結果とのsettlementは別の後続変更で実装・検証中であり、この段階のmain実行modeには含めない。source providerの新規取得、別schedule、別の学習正本、本番pin変更は含めない。

未来証拠として数えるには、保存した原本の生成・暗号化に加え、独立runのserver完了時刻もT−15以前であることが必要。全予定分母、取得できなかった入力、締切超過、未出力、結果未確定、不成立・同着を残す。過去のA/B原本時刻を新DT予測の時計へ転用しない。同一day/race/modelの最初の採用原本を保存側で固定し、別runの再計算で差し替えない。

実producer/readback/settlementのrunと成績は、実行後の証拠で追記する。この文書の実装説明だけでは未来完走済みとしない。

## 残る実証条件

| 工程 | 未達の内容 |
|---|---|
| P2–P3 映像と6局面 | 追加の実動画原本、公式登録IDへの本人照合、全車の局面位置と誤差付き計測が不足。既存125レース267チェックポイントは必要な原本・全車順位・レビュー時計を満たさない。代理特徴を実測の消耗や因果に格上げしない。 |
| P4 5機能の改善 | 固定Hit@1、確率精度、展開誤差について未学習の未来データで効果を確認。参考後続期間の小さい差だけで全面改善とはしない。 |
| P5 正式3者対戦 | 既存統合のA/B50:50という意図とPR404のA=.25/B=.25/研究=.50を混同せず、参加者の実manifestと共通入力契約を固定する。DT単独shadowを3者対戦に数えない。 |
| P6 全国未来完走 | 同じ実レースで予定→新予測→暗号保存→独立読戻し→公式結果→集計を完走し、全国登録分母と網羅率も別記する。 |
| P7 信頼度・オッズ | 90/80/60の閾値は固定。旧校正の未来移転、同時点の完全オッズと公式払戻は別の実証。証拠不足ならconfidence HOLD。 |
| P8 正式採用 | 候補の実測・保全・復旧・独立レビューと所有者承認後にのみ本番pinを変更する。現時点で昇格していない。 |

CI成功と実owner復元成功は重要な受入だが、予想精度改善や将来の的中を証明しない。現在の目標は実際の未発走原本と確定結果を結ぶことであり、未達の工程は未達のまま記録する。
