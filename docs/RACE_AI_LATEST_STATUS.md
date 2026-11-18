# RACE-AI 最新状況 — 2026-11-18 11:18 UTC

**GOALは未達。** この文書は現在の事実だけをまとめる。従来の全文は[履歴](history/RACE_AI_STATUS_HISTORY_THROUGH_20261118_0928.md)へ、同じGit blobのまま保全した。実予想原本・モデル重み・元の判定を変更しない。

## 実行環境・HEAD・保全

- main実装: `653ec7544410e36e4c6002be077f1addf7d950d3`、tree `b67a5d42b596d2edf1c51f7e4ac571d0a5e7ad79`。既存PR31の通常mergeでtested tree一致。364件/199.335秒、15checks＝8success/7skip/失敗0、独立review CLEAR。
- source: `c979aeb678538d99e277f26726047dccbdc982af`、tree `766b8a3ea5d9d3b85e0f399523ede2eb8f1b688b`。PR34の通常mergeでtested tree一致。877/38/165/46件等が成功。mainの現行参照は同期済み。
- 選択実行環境はfailed。実コマンド再試行も利用不可。公開WebのSign in表示ページからrepo/READMEのread成功（cacheでありHEAD証明には使わない）。別にGitHub管理接続の認証済みread・write・通常保護mergeは実成功しており、ローカルCLI認証の検証とは区別する。キーはActions内だけ。
- 元offline変更PR70 `b7380fe6a377e6ccf2b96331f2126c52549bbe17`、PR292 `daae4c10167224b7730006d8ada5ade398aaa64b`は、08:40:39 UTC正規APIが両方422 No commit foundで**未復元**。別環境のファイル移転を仮定しない。
- 新PR・モデル系統・課金・job・workflow input・cron・runner・timeout・権限・marker名・UI公開・投票・本番重み切替を増やさない。既存OFF pilot/PR290/291/main308・legacy KEIRIN-AIも維持する。

## 自動予想と原本

元run43829249080のP0保管失敗と24巡skipは履歴として残す。修正後のA74 run44218343091は24巡success/skip0。正規別runner44268654165と再実行44276148160で24巡の最終control・73AES archive・ALL_MODEL 23 ZIPを認証し、P1 **513行**がsaved AES viewと一致、欠落0。公式P0 scheduleは132レースとして認証した。513行は固有レース数・完全P0/P1 union・適格分母ではない。

round4/19のALL_MODEL ZIPが欠けるため `HOLD_ALL_MODEL_ARCHIVE_ABSENT_UNEXPLAINED`。締切適格数0は全体HOLDの監査結果であり、全行が締切後という証拠ではない。旧実行の正規完了ログではr4はcontexts=0/generated=0の明示分岐、r19は保持locator未選択のartifact metadata/ZIP読取404だった。r4の入力網羅性、r19の対象・404根因は不明で、HOLDを解除しない。[各巡の固定証拠](evidence/boat-a74-round04-round19-source-facts-20261118.json)。以前のr0=660、A74 r0=585、reused285、retained264/waiting924などは対象が異なり、単純合算しない。[実独立監査](evidence/boat-main-sync-closed-a74-actual-20261118.json)。

11:18 UTC現在、後続run44252479726は旧A74のまま1〜10巡success/11巡実行中/failed0。停止・hotswap・counter resetをしていない。cacheと固定理由診断は次の正規source workerからで、実速度改善・T15〜10全件充足は未確認。

## ペア監査の実際の拒否理由

固定理由の補完後、現行の拒否と全受入条件を維持した12項目の締切診断をPR31で反映した。tests-only REDは364件/128.768秒・想定5assert失敗/errors0、実装後は364件/199.335秒すべて成功。通常merge後の実再監査44287428057/job134743588631はsuccess。

正規完了ログ10:48:10 UTCでは、診断対象のfirst-originalは **48レース/672モデルrecord**。42レース588件は締切一致、2レース28件は結果側の予定締切が後、4レース56件は結果観測なし。前倒し0・締切未記録0。これは全132レースの網羅・saved-view P1の513行・適格分母と異なるscopeで、合算しない。元の `PAIR_RESULT_JOIN / ALL_MODEL_INTAKE_RESULT_ACTUAL_CUTOFF_MISMATCH` とcoreの4/19欠落HOLDは維持。正式ペア件数/G8分母はnull。[実件数証拠](evidence/boat-current-pair-cutoff-inventory-actual-20261118.json)。

次は2レースの保存本文から予定時刻表を調べる。当時のproducer parserはデータ形状だけでは断定できないため、固定A74 PROGRAM inspectorと固定pr64 RESULT inspectorを文書の役割ごとに使う。保存時計と固定検査器の一致/相違だけを報告し、当時のparser不具合・公式改定の正当性・実際の発売終了を断定しない。既存A74 vault readerで原本を認証し、本文が未取得か認証できなければHOLD。[読取手順](evidence/boat-current-pair-raw-replay-recipe-20261118.json)。参照26件・185MBのmetadata宣言は認証済み本文の存在証明ではない。既存PR30で固定inspector＋既存A74 reader adapterを実装中。先行CI44291210552/job134756589726では旧364件/128.608秒が全成功、新7件/0.965秒は実AES/HMAC26束の対照1件が成功・未実装モジュールの想定6assert失敗/errors0。呼出側は既存core/pairの後で独立し、認証失敗の件数はnullのまま。新raw最終CI・実原本認証はまだ未確認。[実装計画](superpowers/plans/2026-11-18-saved-cutoff-raw-replay.md)、[先行CI証拠](evidence/boat-current-pair-saved-grid-tdd-20261118.json)。

## 画面・4競技・映像・精度

| 完成条件 | 実確認と残件 |
| --- | --- |
| スマホ/PC・Safari | 実Mac26.6/run44258108084で11/18世代433、結果79/native原本9group、2model原本比較、browser AES成功。固定暗号文loopback再生でありGitHub暗号feed直接配送の証明ではない。物理iPhone・本人login・全8参考画面目視はfalse。ed904候補の28PNGは合成のみ、公開UI f603を変更していない。 |
| 全レース×全適用既存model | BOATは上記の部分実証。完全union/全日/T15〜10/継続日跨ぎは未証明。AUTOの個車入力、JRAとNARの適用区別、4競技全日の独立証明も未完。 |
| 競輪 | 最新canary44236121551は日次indexHTTP403。discovery44222760913の79リンク/8会場はidentity-only。capture/PR71のjob成功もskipまたは入力不完備HOLDで、予想・結果件数はnull。[実4run](evidence/keirin-current-automatic-blockers-20261118.json)。 |
| 6艇の継続識別・校正・予想接続 | 同時6艇の独立GT/承認済み映像/実race結合が未確認。既知Commons映像は2〜3艇で、6艇精度や校正を証明しない。 |
| 前向き精度改善 | 11/3方針073379は事前に存在（100matched/5日/10会場日）。今回nativeセルとの適用は未判定。574 PDCA pairsや過去holdoutを適格分母へしない。本番重み変更0、改善・98%は未実証。 |

競輪の承認は[WINTICKET/KEIRIN.JP限定](https://github.com/haji84/RACE-AI/blob/fe7e5581263b2b31fbd45536ac6a611c2779fa65/docs/KEIRIN_WINTICKET_KEIRINJP_OWNER_SOURCE_APPROVAL_20261109.md)でKdreamsを除外する。許可済みraw/JSON/CSV、7/9人roster・公式締切・critical入力・目的別grantが必要。既存offline取込はある。保管先/設定名だけを本人へ質問済みで、鍵やpasswordをチャットへ要求していない。

既存Actionsの正規実行と通常保護mergeの承認は継続しており、完了したコードを再承認待ちにしない。UI公開・投票・本番重み切替は別であり未実施。未確認を完成扱いしない。
