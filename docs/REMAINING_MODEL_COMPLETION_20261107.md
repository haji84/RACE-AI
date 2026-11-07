# 残枠実装・実データ検証報告（2026-11-07 JST）

**現行30枠のうち実学習は19枠（BOAT14・HORSE5）。新候補の実未来PDCAは通常1レース・BOAT14枠で成立した。現行全30枠の完成ではない。** 残11枠は競輪5、オート6。販売者1枠はリモートの所有者変更で現行対象から除外されたため、学習済みへ加算しない。過去31枠の登録情報・MAC・SHAは保持する。競馬10・オート12・競輪11、計33レース・177 native入力はすべて締切前保存・独立読戻し済み。競馬は公式通常8件・特殊2件を独立認証し、5モデル共通8レースの学習6／検証2が成功した。競輪・オートの結果取得は通信件数不明の予約24件を保持して停止中。未取得の結果を補完しない。

## 最新の実証チェックポイント

- [19枠の実学習](evidence/2026-11-07/nineteen-native-model-fit-counts.json)：152原レコード（BOAT112＋HORSE40）、全19枠が8レース・6学習／2検証、後付け派生0。学習SHA `87840763c2ce2656b85b2b09e3c766950bc67db11c9d467f8e7976284fbd7059`。既定モデル・係数・旧14候補・旧MACは変更しない。
- [競馬8通常結果の独立認証](evidence/2026-11-07/eight-normal-horse-results-authenticated-counts.json)：実GitHub receipt付きの3 RESULT ZIPを復号し、公式原本を再解析。特殊2件は学習対象外。単一の正常レースを複数の独立レースとして数えない。
- [第2回結果収集の停止証跡](evidence/2026-11-07/actual-second-result-collection-hold-counts.json)：[42349536138](https://github.com/haji84/RACE-AI/actions/runs/42349536138)の全workflowは成功したが、AUTO4・KEIRIN2ケースの実収集は失敗。既知のJRA GET8件はすべて200。browser件数は不明、予約上限24・全上限32を維持。実行前plan6件／保存済み静的95件の純粋検証は通るが、実失敗原因を確定できない。
- 旧実装はbrowserの後段検証に失敗すると、返却済みindexと通信件数を暗号journalに保存しなかった。同一UI要求の重複roleでもこの欠陥を再現できるが、実epochの原因だと断定しない。旧journalは改変せず暗号文を追加保管し、次回manifestにも実journal pinを継承する。回数を0に戻したり、再取得・別URLへ切り替えたりしない。
- 19候補は実学習・ローカル暗号化復元まで。既存の未来V1/V2は12／14、V3は30枠専用のため、19候補の実未来PDCAは未実施。BOAT14の成立済みPDCAと混同しない。既存Actionsで19枠を再検証し、保持・独立復元の証跡を追加する。

以下は現時点の指定12項目。先行候補の不変証跡は履歴として保持する。

## 後続の接続実装と検証

[未来baseline・日曜締切・一度限りの復旧手順](NATIVE_FUTURE_BASELINE_AND_REVIEWED_RECOVERY_20261107.md)を追加した。新19候補の実artifactでは係数・支持数・holdoutがローカルと一致し、432座標中174支持・171変更だった。全Python3,456件は成功（skip310）したが、動画fixtureの末尾フレーム数不一致でActions全体は失敗した。fixture修正後の固定依存による動画461件は成功。新V4・JRA V3・packet V2・復旧入口は合成E2E／原文規則／既存形式回帰で検証し、実未来成功へ加算しない。限定再取得のcapsuleは未発行、提供元アクセス0のまま。

## 保存・実行の後続証跡

- [19候補2世代と追加4結果の暗号保存・独立復元](evidence/2026-11-07/nineteen-candidates-and-epoch2-retention-counts.json)：元ファイル・ZIP・metadataとバイト一致。新しい不変パスだけを追加し、既定モデルへの参照は変更しない。
- [08b587a2の全体CI attempt 1成功](evidence/2026-11-07/reviewed-head-full-ci-attempt1-counts.json)。初回の取得入口はcapsule未発行で提供元アクセス0。
- [期限間近のattempt 2を取得前に停止](evidence/2026-11-07/expired-fixed-probe-zero-dispatch-counts.json)：provider stepはskipped、実取得0。旧capsule・旧UNKNOWNのSHAは保持する。次のHEADでは同一HEADの全体検証済み証拠を使う限定再実行を検証し、新しい記録を発行する。

## 指定12項目

| 項目 | 実証内容と限界 |
| --- | --- |
| 1. 調査したAPI・経路 | 艇愛の仕様・利用条件・実取得は[既存の調査記録](TEIAI_HISTORY_INTEGRATION.md)を継承。今回の追加艇愛APIアクセスは0。新規の実取得はJRAの凍結カードから実際に公開された結果GETリンク。AUTOのLive通常画面、KEIRINのtop→出走表一覧→競走結果の既存通常UI経路も実装し、入力取得と結果取得を分けた。APIの存在から学習・再配布許諾を推定していない |
| 2. 実取得できたもの | BOAT112原入力、非BOAT33レース・177原入力と実取得時計・締切前receipt。競馬は通常8・特殊2の公式結果。19枠の実学習はBOAT112＋HORSE40＝152原レコード。未提供値は欠測のまま |
| 3. 未取得項目 | AUTO／KEIRINの学習用各8正常結果。全選手・全会場・全期間の欠測0、全訂正履歴、公表時刻不明値の当時利用可能性は未実証 |
| 4. 正確性と件数 | 艇愛対公式Kの既存照合は2レース・延べ8行／独立7出走に限定。追加HORSE公式10結果を凍結入力の名簿・日付・場・Rと照合し、通常8・特殊2。BOAT未来は通常1レース・6登録選手・14組、別の特殊1件は正式評価外。全体精度100%や14独立レースとは報告しない |
| 5. 接続特徴量 | 既存nativeの選手・会場履歴、コース/ST、進入・展開、モーター、直近成績・母数・欠測・lineageと、HORSEの実提供特徴量。支持された既存座標だけを学習し、原式と既定係数を保持。19枠の実fit成功。HORSE5共通8件・6/2は今回の実intakeを独立検証した条件であり、keep-other-sportsフラグだけで8件を保証するものではない |
| 6. ファイル一覧 | [この接続作業の変更一覧](evidence/2026-11-07/remaining-native-model-changed-files.json)。PR71全体には並行するUI・動画の変更も含まれる。原本・旧MAC・古いmanifestは保持 |
| 7. テスト | 全Python3,438件（skip297、失敗0）と後段動画283件を含む既存Actions42348678198が全体成功。42349536138も全体成功。ただし取得6ケースHOLDを学習成功へ加算しない。新しい重複応答のNode21件、CI／共通cohort16件が成功。通信件数と隔離の追加検査・最新HEADのActions結果は追記する。30枠E2Eは合成であり実30学習ではない |
| 8. Actions URL | [14枠実fit42334526055](https://github.com/haji84/RACE-AI/actions/runs/42334526055)、[元未来保存42336097863](https://github.com/haji84/RACE-AI/actions/runs/42336097863)、[公式結果42342290428](https://github.com/haji84/RACE-AI/actions/runs/42342290428)、[全体検査42348678198](https://github.com/haji84/RACE-AI/actions/runs/42348678198)、[第2回結果収集42349536138](https://github.com/haji84/RACE-AI/actions/runs/42349536138)。最新19枠のCI結果は別チェックポイントへ固定する |
| 9. HEAD SHA | 14実fitは8cf76d3d023591a4c67d04a0001465ac32b441c5、元未来保存は013c59c3f41209993bfba1f4b2b93791deba3d6c、通常結果はdf05282fc85265b99c43141c74dff678a53518ac。19ローカル学習SHAは87840763c2ce2656b85b2b09e3c766950bc67db11c9d467f8e7976284fbd7059。最新実装HEADとCI学習SHAは検証後に別記する |
| 10. 実動作範囲 | BOAT14の実6/2学習→キー復元→同一入力の基準／学習版の締切前独立保存→登録6人照合→14組PDCA→28暗号化partition別復元→再実行拒否・85ファイルSHA不変。HORSE5は実8件・6/2学習とローカル暗号化復元まで。19候補の未来PDCA・本番運用成功ではない |
| 11. 未完成と原因 | 現行対象の残11枠。AUTO6・KEIRIN5は取得失敗の実通信件数が不明で、予約24件を保持して再取得停止。販売者は[所有者の除外変更](BOAT_SELLER_RETIREMENT_20261107.md)により現行対象外。HORSE未来は新しい締切前入力と明示されたgenuine ranker baselineの接続・独立保存・結果照合が未実施。全期間欠測0と十分な前向き標本も未実証。所有者キーによる実復元は確認済みであり、旧キー不足を阻害理由にしない |
| 12. 次の最小工程 | 新19候補を既存Actionsで再学習・独立読戻しし、暗号化保持する。AUTO／KEIRINは保存済み失敗journalを維持し、原本と通信会計を確認できるまで再取得しない。通常8件が各競技で揃った後、公開runbookの30枠×8＝240原レコード、32独立レースの実6/2fitへ進める。新しい未来入力の凍結時にgenuine baselineを結び付け、既存の独立保存→公式結果→PDCAを通す。削除した売主型の入力取得は不要 |

## 実証へのリンク

- [14枠CIと非BOAT88入力](evidence/2026-11-07/fourteen-ci-and-nonboat-freeze-counts.json)
- [予備7レースの実保存](evidence/2026-11-07/seven-reserve-native-counts.json)
- [初回収集：実8GET・競馬4通常結果](evidence/2026-11-07/actual-first-result-collection-counts.json)
- [新14枠の通常1レースPDCA・特殊除外・再実行拒否](evidence/2026-11-07/fourteen-native-model-future-pdca-counts.json)
- [係数を変えない次回検証候補](evidence/2026-11-07/fourteen-native-model-next-review-counts.json)

これらは各段階の不変スナップショット。後続の保持・Checksは別の証跡へ追加し、元の評価SHAを変更しない。

## 後続の原本保持

巡回42342290428は4巡・146/240 GET、lifetime8940 GET／521巡、`BOUNDED_SESSION_END`、source_wait=nullで正常終了。旧上限・間隔・カウンターを変更していない。[実controlとcontinuity照合](evidence/2026-11-07/same-cap-four-round-source-counts.json)。その後、元ZIP／元metadata5件と、新14枠の通常PDCA14件＋次回検討1件を既存refsへ保持し、別GitオブジェクトDBで原本一致を確認した。競馬の追加4通常結果も独立復元した。旧評価スナップショットのSHAは変更しない。

- [元原本5件の保持・独立復元](evidence/2026-11-07/five-original-archives-retention-counts.json)
- [14枠PDCAと次回検討の15件保持・独立復元](evidence/2026-11-07/fourteen-native-model-future-pdca-retention-counts.json)
- [新しい競馬4結果の保持・独立復元](evidence/2026-11-07/four-new-horse-results-retention-counts.json)

残る条件は引き続き17枠の実学習と実30未来・十分な標本、売主型の本来の入力。原本保持の成功を学習成功へ加算しない。
